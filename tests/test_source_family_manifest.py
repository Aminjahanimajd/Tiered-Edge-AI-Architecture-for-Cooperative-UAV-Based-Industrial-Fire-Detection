import unittest

from tools.build_source_family_manifest import source_family_group_id


def record(record_id, group_id="old"):
    return {"record_id": record_id, "group_id": group_id}


class SourceFamilyManifestTests(unittest.TestCase):
    def test_img_capture_variants_share_one_conservative_family(self):
        first = source_family_group_id(
            record("base/train/IMG_3840-1-_jpeg_jpg.rf.abcdef0123456789.jpg")
        )
        second = source_family_group_id(
            record("base/valid/IMG_5735_jpeg_jpg.rf.0123456789abcdef.jpg")
        )
        self.assertEqual(first, second)

    def test_numbered_house_frames_share_family_but_houses_do_not(self):
        house_four_a = source_family_group_id(
            record("base/train/HouseFour208_png.rf.abcdef0123456789.jpg")
        )
        house_four_b = source_family_group_id(
            record("base/valid/HouseFour186_png.rf.0123456789abcdef.jpg")
        )
        house_five = source_family_group_id(
            record("base/test/HouseFive606_png.rf.1111111111111111.jpg")
        )
        self.assertEqual(house_four_a, house_four_b)
        self.assertNotEqual(house_four_a, house_five)

    def test_negative_group_is_preserved_before_reviewed_merges(self):
        value = source_family_group_id(
            record("negative/train/fogsmog (10).jpg", "negative/source/hash")
        )
        self.assertEqual(value, "negative/source/hash")


if __name__ == "__main__":
    unittest.main()
