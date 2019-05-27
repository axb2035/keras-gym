import logging

import numpy as np
from gym.envs.toy_text.frozen_lake import FrozenLakeEnv, LEFT, RIGHT, UP, DOWN

from keras_gym.utils import TrainMonitor
from keras_gym.preprocessing import DefaultPreprocessor
from keras_gym.policies import LinearSoftmaxPolicy, ActorCritic
from keras_gym.value_functions import LinearV


logging.basicConfig(level=logging.INFO)


# env with preprocessing
actions = {LEFT: 'L', RIGHT: 'R', UP: 'U', DOWN: 'D'}
env = FrozenLakeEnv(is_slippery=False)
env = DefaultPreprocessor(env)
env = TrainMonitor(env)


# updateable policy
policy = LinearSoftmaxPolicy(env, lr=0.1, update_strategy='ppo')
V = LinearV(env, lr=0.1, gamma=0.9, bootstrap_n=1)
actor_critic = ActorCritic(policy, V)


# static parameters
target_model_sync_period = 20
num_episodes = 500
num_steps = 30


# train
for ep in range(num_episodes):
    s = env.reset()

    for t in range(num_steps):
        a = policy(s, use_target_model=True)
        s_next, r, done, info = env.step(a)

        # small incentive to keep moving
        if np.array_equal(s_next, s):
            r = -0.1

        actor_critic.update(s, a, r, done)

        if env.T % target_model_sync_period == 0:
            policy.sync_target_model(tau=1.0)

        if done:
            break

        s = s_next


# run env one more time to render
s = env.reset()
env.render()

for t in range(num_steps):

    # print individual action probabilities
    print("  V(s) = {:.3f}".format(V(s)))
    for i, p in enumerate(policy.proba(s)):
        print("  π({:s}|s) = {:.3f}".format(actions[i], p))

    a = policy.greedy(s)
    s, r, done, info = env.step(a)
    env.render()

    if done:
        break
