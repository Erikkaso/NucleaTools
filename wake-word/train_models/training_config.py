"""Bounded, reproducible parameter sampling for a single training experiment."""
import math
import random


def training_config(seed: int, randomize: bool = False) -> dict:
    if not isinstance(seed, int) or not 0 <= seed < 2**31:
        raise ValueError('Seed must be an integer between 0 and 2**31 - 1.')
    config = {'seed': seed, 'randomized': randomize, 'learning_rate': .0007,
              'dropout': .3, 'batch_size': 64}
    if randomize:
        rng = random.Random(seed)
        config.update(learning_rate=math.exp(rng.uniform(math.log(.0003), math.log(.001))),
                      dropout=rng.choice((.2, .3, .4)), batch_size=rng.choice((32, 64)))
    return config
