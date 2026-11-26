import unittest

import numpy as np

from ambilight import Settings, dominant_from_bgr, lerp_hsv, pick_monitor, settings_from_mapping


class DominantColorTest(unittest.TestCase):
    def test_black_frame_is_dim_idle(self):
        image = np.zeros((20, 20, 3), np.uint8)
        self.assertEqual(dominant_from_bgr(image, Settings()), (8, 14, 26))

    def test_white_frame_is_capped_idle(self):
        image = np.full((20, 20, 3), 255, np.uint8)
        self.assertEqual(dominant_from_bgr(image, Settings()), (18, 32, 60))

    def test_gray_with_red_accent_stays_red(self):
        image = np.full((30, 30, 3), 140, np.uint8)
        image[0:4, 0:4] = (0, 0, 230)  # BGR
        red, green, blue = dominant_from_bgr(image, Settings())
        self.assertGreaterEqual(red, 200)
        self.assertLessEqual(green, 15)
        self.assertLessEqual(blue, 15)

    def test_majority_green_beats_red(self):
        red = np.zeros((10, 10, 3), np.uint8)
        red[..., 2] = 220
        green = np.zeros((10, 40, 3), np.uint8)
        green[..., 1] = 220
        image = np.concatenate([red, green], axis=1)
        red_ch, green_ch, blue_ch = dominant_from_bgr(image, Settings())
        self.assertGreaterEqual(green_ch, 200)
        self.assertLessEqual(red_ch, 15)
        self.assertLessEqual(blue_ch, 15)

    def test_majority_blue_does_not_mix_with_red(self):
        blue = np.zeros((20, 20, 3), np.uint8)
        blue[..., 0] = 210
        red = np.zeros((20, 4, 3), np.uint8)
        red[..., 2] = 210
        image = np.concatenate([blue, red], axis=1)
        red_ch, green_ch, blue_ch = dominant_from_bgr(image, Settings())
        self.assertGreaterEqual(blue_ch, 200)
        self.assertLessEqual(red_ch, 15)
        self.assertLessEqual(green_ch, 15)

    def test_equal_opposites_stay_pure(self):
        red = np.zeros((20, 20, 3), np.uint8)
        red[..., 2] = 220
        green = np.zeros((20, 20, 3), np.uint8)
        green[..., 1] = 220
        image = np.concatenate([red, green], axis=1)
        color = dominant_from_bgr(image, Settings())
        ordered = sorted(color)
        self.assertGreaterEqual(ordered[-1], 200)
        self.assertLessEqual(ordered[-2], 15)


class SmoothingTest(unittest.TestCase):
    def test_hsv_lerp_reaches_target(self):
        state = (0.0, 1.0, 1.0)
        target = (0.0, 1.0, 100 / 255)
        for _ in range(40):
            state = lerp_hsv(state, target, 0.4)
        self.assertAlmostEqual(state[2], 100 / 255, places=2)

    def test_hue_takes_the_short_path(self):
        hue, _saturation, _value = lerp_hsv((10.0, 1.0, 1.0), (350.0, 1.0, 1.0), 0.5)
        self.assertAlmostEqual(hue, 0.0, places=5)


class SettingsTest(unittest.TestCase):
    def test_mapping_clamps_and_filters_devices(self):
        settings, unknown = settings_from_mapping(
            {"fps": 100, "hue_bins": 2, "exclude_devices": ["Keyboard", "nope"], "on_exit": "nope"}
        )
        self.assertEqual(settings.fps, 30.0)
        self.assertEqual(settings.hue_bins, 6)
        self.assertEqual(settings.exclude_devices, ("keyboard",))
        self.assertEqual(unknown, ["nope"])
        self.assertEqual(settings.on_exit, "leave")

    def test_pick_monitor(self):
        monitors = [{"all": True}, {"primary": True}, {"second": True}]
        self.assertTrue(pick_monitor(monitors, 1)["primary"])
        self.assertTrue(pick_monitor(monitors, 9)["primary"])
        self.assertTrue(pick_monitor(monitors, 0)["all"])
        self.assertTrue(pick_monitor(monitors, 2)["second"])


if __name__ == "__main__":
    unittest.main()
