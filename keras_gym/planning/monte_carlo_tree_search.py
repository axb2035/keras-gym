from copy import deepcopy

import numpy as np

from ..base.mixins import NumActionsMixin, RandomStateMixin
from ..base.errors import LeafNodeError, NotLeafNodeError, EpisodeDoneError
from ..utils import argmax, one_hot

__all__ = (
    'MCTSNode',
)


class MCTSNode(NumActionsMixin, RandomStateMixin):
    """
    Implementation of Monte Carlo tree search used in AlphaZero.

    Parameters
    ----------
    state_id : str

        The state id of the env, which allows us to set the env to the correct
        state.

    actor_critic : ActorCritic object

        The actor-critic that is used to evaluate leaf nodes.

    tau : float, optional

        The temperature parameter used in the 'behavior' policy:

        .. math::

            \\pi(a|s)\\ =\\
                \\frac{N(s,a)^{1/\\tau}}{\\sum_{a'}N(s,a')^{1/\\tau}}

    v_resign : float, optional

        The value we use to determine whether a player should resign before a
        game ends. Namely, the player will resign if the predicted value drops
        below :math:`v(s) < v_\\text{resign}`.

    c_puct : float, optional

        A hyperparameter that determines how to balance exploration and
        exploitation. It appears in the selection criterion during the *search*
        phase:

        .. math::

            a\\ =\\ \\arg\\max_{a'}\\left( Q(s,a) + U(s,a) \\right)

        where

        .. math::

            Q(s,a)\\ &=\\ \\frac1{N(s)}
                \\sum_{s'\\in\\text{desc}(s,a)} v(s') \\\\
            U(s,a)\\ &=\\ \\color{red}{c_\\text{puct}}\\,P(s, a)\\,
                \\frac{\\sqrt{N(s)}}{1+N(s,a)}

        Here :math:`\\text{desc}(s,a)` denotes the set of all the previously
        evaluated descendant states of the state :math:`s` that can be reached
        by taking action :math:`a`. The value and prior probabilities
        :math:`v(s)` and :math:`P(s,a)` are generated by the actor-critic.
        Also, we use the short-hand notation for the combined state-action
        visit counts:

        .. math::

            N(s)\\ =\\ \\sum_{a'} N(s,a')

        Note that this is not exactly the state visit count, which would be
        :math:`N(s) + 1` due to the initial selection and expansion of the root
        node itself.

    random_seed : int, optional

        Sets the random state to get reproducible results.


    Attributes
    ----------
    is_root : bool

        Whether the current node is a root node, i.e. whether it has a parent
        node.

    is_leaf : bool

        Whether the current node is a leaf node. A leaf node is typically a
        node that was previous unexplored, but it may also be a terminal state
        node.

    is_terminal : bool

        Whether the current state is a terminal state.

    parent_node : MCTSNode object

        The parent node. This is used to traverse back up the tree.

    parent_action : int

        Which action led to the current state from the parent state. This is
        used to inform the parent which child is responsible for the update in
        the *backup* phase of the search procedure.

    children : dict

        A dictionary that contains all the child states accessible from the
        current state, format: ``{action <int>: child <MCTSNode>}``.

    U : 1d array, dtype: float, shape: [num_actions]

        The UCT exploration term, which is a vector over the space of actions:

        .. math::

            U(s,a)\\ =\\ c_\\text{puct}\\,P(s,a)\\,
                \\frac{\\sqrt{N(s)}}{1+N(s,a)}

    Q : 1d array, dtype: float, shape: [num_actions]

        The UCT exploitation term, which is a vector over the space of actions:

        .. math::

            Q(s,a)\\ =\\ \\frac{W(s,a)}{N(s, a)}

        Here :math:`\\text{desc}(s,a)` denotes the set of all the previously
        evaluated descendant states of the state :math:`s` that can be reached
        by taking action :math:`a`. The value and prior probabilities
        :math:`v(s)` and :math:`P(s,a)` are generated by the actor-critic.

    W : 1d array, dtype: float, shape: [num_actions]

        This is the accumulator for the numerator of the UCT exploitation term
        :math:`Q(s,a)`, which is a vector over the space of actions:

        .. math::

            W(s,a)\\ =\\ v(s) + \\sum_{s'\\in\\text{desc}(s,a)} v(s')

        Here :math:`\\text{desc}(s,a)` denotes the set of all the previously
        evaluated descendant states of the state :math:`s` that can be reached
        by taking action :math:`a`. The value and prior probabilities
        :math:`v(s)` and :math:`P(s,a)` are generated by the actor-critic.

    N : 1d array, dtype: int, shape: [num_actions]

        The state-action visit count :math:`N(s,a)`.

    D : 1d array, dtype: bool, shape: [num_actions]

        This contains the ``done`` flags for each child state, i.e. whether
        each child state is a terminal state.

    env : gym-style environment

        The main environment of the game.

    state : state observation

        The current state of the environment.

    num_actions : int

        The number of actions of the environment, i.e. regardless of whether
        these actions are actually available in the current state.


    """
    def __init__(
            self,
            actor_critic,
            state_id=None,
            tau=1.0,
            v_resign=0.999,
            c_puct=1.0,
            random_seed=None):

        self.actor_critic = actor_critic
        self.tau = tau
        self.v_resign = v_resign
        self.c_puct = c_puct
        self.random_seed = random_seed  # also sets self.random

        # set/reset env
        self.env = deepcopy(self.actor_critic.env)
        if state_id is None:
            self.env.reset()
        else:
            self.env.set_state(state_id)
        self.state_id = self.env.state_id
        self.state = self.env.state
        self.is_terminal = self.env.done

        # these are set/updated dynamically
        self.parent_node = None
        self.parent_action = None
        self.children = {}
        self.is_leaf = True
        self.v_abs_max = 0
        self.v = None
        self.P = None

    def __repr__(self):
        s = "MCTSNode('{}', v={:s} done={}".format(
            self.state_id, self._str(self.v, length=5, suffix=','),
            self._str(self.is_terminal, suffix=')', length=5))
        return s

    def reset(self):
        self.__init__(
            actor_critic=self.actor_critic,
            state_id=None,
            tau=self.tau,
            v_resign=self.v_resign,
            c_puct=self.c_puct,
            random_seed=self.random_seed)

    def search(self, n=512):
        """
        Perform :math:`n` searches.

        Each search consists of three consecutive steps: :func:`select`,
        :func:`expand` and :func:`backup`.

        Parameters
        ----------
        n : int, optional

            The number of searches to perform.

        """
        for _ in range(n):
            leaf_node = self.select()
            v = leaf_node.v if leaf_node.is_terminal else leaf_node.expand()
            leaf_node.backup(v)

    def play(self, tau=None):
        """
        Play one move/action.

        Parameters
        ----------
        tau : float, optional

            The temperature parameter used in the 'behavior' policy:

            .. math::

                \\pi(a|s)\\ =\\
                    \\frac{N(s,a)^{1/\\tau}}{\\sum_{a'}N(s,a')^{1/\\tau}}

            If left unspecified, ``tau`` defaults to the instance setting.

        Returns
        -------
        s, a, pi, r, done : tuple

            The return values represent the following quanities:

            s : state observation
                The state :math:`s` from which the action was taken.

            a : action
                The specific action :math:`a` taken from that state :math:`s`.

            pi : 1d array, dtype: float, shape: [num_actions]
                The action probabilities :math:`\\pi(.|s)` that were used.

            r : float
                The reward received in the transition
                :math:`(s,a)\\to s_\\text{next}`

            done : bool
                A flag that indicates that either the game has finished or the
                actor-critic predicted a value that is below the cutoff value
                :math:`v(s) < v_\\text{resign}`.

        """
        if self.is_leaf:
            raise LeafNodeError(
                "cannot play from a leaf node; must search first")

        if tau is None:
            tau = self.tau

        # construct pi(a|s) ~ N(s,a)^1/tau
        if tau < 0.1:
            # no need to compute pi if tau is very small
            a = argmax(self.N, random_state=self.random)
            pi = one_hot(a, self.num_actions)
        else:
            pi = np.power(self.N, 1 / tau)
            pi /= np.sum(pi)
            a = self.random.choice(self.num_actions, p=pi)

        # this will become the new root node
        child = self.children[a]

        # update env
        s = self.state
        s_next, r, done, info = self.env.step(a)
        assert child.state_id == info['state_id']

        # switch to new root node
        child.parent_node = None
        child.parent_action = None
        self.__dict__.update(child.__dict__)

        return s, pi, r, done  # or self.v_abs_max < self.v_resign

    def select(self):
        """
        Traverse down the tree to find a leaf node to expand.

        Returns
        -------
        leaf_node : MCTSNode object

            The selected leaf node.

        """
        if self.is_leaf:
            return self

        # pick action according to PUCT algorithm
        a = max(self.children.keys(), key=(lambda a: self.Q[a] + self.U[a]))
        child = self.children[a]

        # recursively traverse down the tree
        return child.select()

    def expand(self):
        """
        Expand tree, i.e. promote leaf node to a non-leaf node.

        Returns
        -------
        v : float

            The value of the leaf node as predicted by the actor-critic.

        """
        if not self.is_leaf:
            raise NotLeafNodeError(
                "node is not a leaf node; cannot expand node more than once")
        if self.is_terminal:
            raise EpisodeDoneError("cannot expand further; episode is done")

        self.P, v = self.actor_critic.proba(self.state)
        if self.v is None:
            self.v = float(v)

        # make TrainMonitor quiet
        if hasattr(self.env, 'quiet'):
            quiet_orig, self.env.quiet = self.env.quiet, True

        for a in self.env.available_actions:
            s_next, r, done, info = self.env.step(a)
            child = MCTSNode(
                self.actor_critic,
                state_id=info['state_id'],
                tau=self.tau,
                v_resign=self.v_resign,
                c_puct=self.c_puct,
                random_seed=self.random_seed)
            child.random = self.random
            child.parent_node = self
            child.parent_action = a
            if done:
                self.D[a] = True
                child.v = -r  # note: flip sign for 'opponent'
            self.children[a] = child
            self.env.set_state(self.state_id)  # reset state to root

        # reinstate original 'quiet' flag in TrainMonitor
        if hasattr(self.env, 'quiet'):
            self.env.quiet = quiet_orig

        # after expansion, this is no longer a leaf node
        self.is_leaf = False

        return self.v

    def backup(self, v):
        """
        Back-up the newly found leaf node value up the tree.

        Parameters
        ----------
        v : float

            The value of the newly expanded leaf node.

        """
        if self.is_leaf and not self.is_terminal:
            raise LeafNodeError(
                "node is a leaf node; cannot backup before expanding")

        self.v_abs_max = max(self.v_abs_max, np.abs(v))

        # recursively traverse up the tree
        if not self.is_root:
            # notice that we flip sign for 'opponent'
            self.parent_node.N[self.parent_action] += 1
            self.parent_node.W[self.parent_action] += -v
            self.parent_node.backup(-v)

    @property
    def U(self):
        if self.is_leaf:
            U = None
        else:
            # PUCT: U(s,a) = P(s,a) sqrt(sum_b N(s,b)) / (1 + N(s,a))
            U = self.c_puct * self.P * np.sqrt(np.sum(self.N)) / (1 + self.N)
            U[self.D | (~self.env.available_actions_mask)] = 0
        return U

    @property
    def Q(self):
        if self.is_leaf:
            Q = None
        else:
            Q = self.W / (self.N + 1e-16)
            Q[self.D] = self.env.win_reward
            Q[~self.env.available_actions_mask] = self.env.loss_reward
        return Q

    @property
    def N(self):
        if not hasattr(self, '_N'):
            self._N = np.zeros(self.num_actions, dtype='int')
        return self._N

    @property
    def W(self):
        if not hasattr(self, '_W'):
            self._W = np.zeros(self.num_actions, dtype='float')
        self._W[~self.env.available_actions_mask] = -np.inf
        return self._W

    @property
    def D(self):
        if not hasattr(self, '_D'):
            self._D = np.zeros(self.num_actions, dtype='bool')
        return self._D

    @property
    def is_root(self):
        return self.parent_node is None

    def show(self, max_depth=None):
        """
        Visualize the search tree. Prints to stdout.

        Parameters
        ----------
        max_depth : positive int, optional

            The maximal depth to visualize. If left unspecified, the full
            search tree is shown.

        """
        if max_depth is None:
            max_depth = np.inf
        self._show(depth=max_depth, prefix='', suffix='')

    def _show(self, depth, prefix, suffix):
        if depth == 0:
            return
        print(prefix + str(self) + suffix)
        if self.children and depth > 1:
            print()
        for a, child in self.children.items():
            child._show(
                depth=(depth - 1),
                prefix=(prefix + "    "),
                suffix=(
                    "  a={:d}  Q={:s}  U={:s}  N={:s}"
                    .format(
                        a, self._str(self.Q[a]), self._str(self.U[a]),
                        self._str(self.N[a]))))
            if a == 6 and depth > 1:
                print()

    @staticmethod
    def _str(x, suffix='', length=5):
        if isinstance(x, (float, np.float32, np.float64)):
            x = '{:g}'.format(x)
        s = str(x)[:length].strip() + suffix
        s += ' ' * max(0, length + len(suffix) - len(s))
        return s
