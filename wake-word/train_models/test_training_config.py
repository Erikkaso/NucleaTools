import unittest

from training_config import training_config


class TrainingConfigTests(unittest.TestCase):
    def test_default_parameters_preserve_previous_training(self):
        self.assertEqual(training_config(42), {
            'seed': 42, 'randomized': False, 'learning_rate': .0007,
            'dropout': .3, 'batch_size': 64,
        })

    def test_randomized_parameters_are_reproducible_and_bounded(self):
        first = training_config(42, randomize=True)
        self.assertEqual(first, training_config(42, randomize=True))
        self.assertNotEqual(first, training_config(43, randomize=True))
        self.assertGreaterEqual(first['learning_rate'], .0003)
        self.assertLessEqual(first['learning_rate'], .001)
        self.assertIn(first['dropout'], (.2, .3, .4))
        self.assertIn(first['batch_size'], (32, 64))

    def test_invalid_seed_is_rejected(self):
        for seed in (-1, 2**31, 1.5):
            with self.assertRaises(ValueError):
                training_config(seed, randomize=True)


if __name__ == '__main__':
    unittest.main()
