import numpy as np

from ..utils import ExperienceCache, accumulate_rewards
from ..policies import GenericActorCritic

from .base import BasePolicyAlgorithm, BaseAlgorithm


class Reinforce(BasePolicyAlgorithm):
    """
    Update the policy according to the REINFORCE algorithm, cf. Section 13.3 of
    `Sutton & Barto <http://incompleteideas.net/book/the-book-2nd.html>`_.

    Parameters
    ----------
    policy : updateable policy

        An updateable policy object, see :mod:`keras_gym.policies`.

    batch_update : bool, optional

        Whether to perform the updates in batch (entire episode). If not, the
        updates are processed one timestep at a time.

    gamma : float

        Future discount factor, value between 0 and 1.

    experience_cache_size : positive int, optional

        If provided, we populate a presisted experience cache that can be used
        for (asynchronous) experience replay. If left unspecified, no
        experience_cache is created. The specific value depends on your
        application. If you pick a value that's too big you might have issues
        coming from the fact early samples are less representative of the data
        generated by the current policy. Of course, there are physical
        limitations too. If you pick a value that's too small you might also
        end up with a sample that's insufficiently representative. So, the
        right value balances negative effects from remembering too much and
        forgetting too quickly.

    Attributes
    ----------
    experience_cache : ExperienceCache or None

        The persisted experience cache, which could be used for (asynchronous)
        experience-replay type updates.

    """
    def __init__(self, policy, batch_update=False, gamma=0.9):
        self.batch_update = batch_update
        self._episode_cache = ExperienceCache(overflow='grow')
        super().__init__(policy, gamma=gamma)

    def update(self, s, a, r, s_next, done):
        """
        Update the policy.

        Parameters
        ----------
        s : int or array

            A single observation (state).

        a : int or array

            A single action.

        r : float

            Reward associated with the transition
            :math:`(s, a)\\to s_\\text{next}`.

        done : bool

            Whether the episode is done. If ``done`` is ``False``, the input
            transition is cached and no actual update will take place. Once
            ``done`` is ``True``, however, the collected cache from the episode
            is unrolled, replaying the epsiode in reverse chronological order.
            This is when the actual updates are made.

        """
        X, A, R, X_next = self.preprocess_transition(s, a, r, s_next)
        self._episode_cache.append(X, A, R)

        # break out of function if episode hasn't yet finished
        if not done:
            return

        if self.batch_update:

            # get data from cache
            X = self._episode_cache[0].array
            A = self._episode_cache[1].array
            R = self._episode_cache[2].array

            # use (non-centered) return G as recorded advantages
            G = accumulate_rewards(R, self.gamma)
            advantages = G

            # keep experience
            if self.experience_cache is not None:
                self.experience_cache.append(X, A, advantages)

            # batch update (play batch in reverse)
            self.policy.update(X, A, advantages)

            # clear cache for next episode
            self._episode_cache.clear()

        else:

            # initialize return
            G = 0

            # replay episode in reverse order
            while self._episode_cache:
                X, A, R = self._episode_cache.pop()

                # use (non-centered) return G as recorded advantages
                G = R + self.gamma * G
                advantages = G

                # keep experience
                if self.experience_cache is not None:
                    self.experience_cache.append(X, A, advantages)

                self.policy.update(X, A, advantages)


class AdvantageActorCritic(BaseAlgorithm):
    """
    Implementation of the advantage actor-critic (A2C) algorithm.

    In A2C, we learn both a policy :math:`\\hat{\\pi}(a|s)` (actor) as
    well as a state value function :math:`\\hat{v}(s)` (critic).

    This algorithm either takes an actor-critic object, see e.g.
    :class:`GenericActorCritic <keras_gym.policies.GenericActorCritic>` or it
    takes both the policy and value function as separate arguments.

    Parameters
    ----------
    actor_critic : actor-critic object, optional

        This is usually just a wrapper that bundles the policy and value
        function into one object. This argument is required of ``policy`` and
        ``value_function`` are left unspecified.

    policy : policy object, optional

        A policy object representing :math:`\\pi(a|s)`, see
        :mod:`keras_gym.policies`. This argument is required of
        ``actor_critic`` is left unspecified.

    value_function : value function object, optional

        A value function object representing :math:`V(s)`, see
        :mod:`keras_gym.value_functions`. This argument is required of
        ``actor_critic`` is left unspecified.

    n : int

        Number of steps to delay bootstrap estimation. If n > 1, we use
        forward-view n-step bootstrapping to estimate :math:`V(s)`.

    experience_cache_size : positive int, optional

        If provided, we populate a presisted experience cache that can be used
        for (asynchronous) experience replay. If left unspecified, no
        experience_cache is created. The specific value depends on your
        application. If you pick a value that's too big you might have issues
        coming from the fact early samples are less representative of the data
        generated by the current policy. Of course, there are physical
        limitations too. If you pick a value that's too small you might also
        end up with a sample that's insufficiently representative. So, the
        right value balances negative effects from remembering too much and
        forgetting too quickly.

    gamma : float

        Future discount factor, value between 0 and 1.

    Attributes
    ----------
    experience_cache : ExperienceCache or None

        The persisted experience cache, which could be used for (asynchronous)
        experience-replay type updates.



    """
    def __init__(self, actor_critic=None, policy=None, value_function=None,
                 n=1, experience_cache_size=0, gamma=0.9):

        self._set_actor_critic(actor_critic, policy, value_function)
        self.n = n
        self._nstep_cache = ExperienceCache(maxlen=n, overflow='error')
        self.experience_cache = None
        if experience_cache_size:
            self.experience_cache = ExperienceCache(
                maxlen=experience_cache_size, overflow='cycle')

        # private
        self._gammas = np.power(self.gamma, np.arange(self.n))

    def update(self, s, a, r, s_next, done):
        """
        Update the underlying actor-critic object.

        Parameters
        ----------
        s : state observation

            A single state observation.

        a : action

            A single action a

        r : float

            Reward associated with the transition
            :math:`(s, a)\\to s_\\text{next}`.

        s_next : state observation

            A single state observation. This is the state for which we will
            compute the estimated future return, i.e. bootstrapping.

        done : bool

            Whether the episode is done. If ``done`` is ``False``, the input
            transition is cached and no actual update will take place. Once
            ``done`` is ``True``, however, the collected cache from the episode
            is unrolled, replaying the epsiode in reverse chronological order.
            This is when the actual updates are made.

        """
        #TODO: implement


    def _set_actor_critic(self, actor_critic, policy, value_function):
        """ set self.actor_critic whilst checking for consistent input """
        if actor_critic is not None:
            if policy is not None:
                raise TypeError(
                    "`policy` must be left unspecified if `actor_critic` is "
                    "provided")
            if value_function is not None:
                raise TypeError(
                    "value_function must be left unspecified if "
                    "`actor_critic` is provided")
            self.actor_critic = actor_critic
        elif policy is not None:
            if value_function is not None:
                raise TypeError(
                    "`value_function` must be provided if `policy` is "
                    "provided too")
            self.actor_critic = GenericActorCritic(policy, value_function)
        elif value_function is not None:
            raise TypeError(
                "`policy` must be provided if `value_function` is "
                "provided too")
        else:
            raise TypeError(
                "either `actor_critic` must be provided of both `policy` and "
                "`value_function`")
