#!/usr/bin/env python3
"""Dataset compatibility fixes for TFLite Model Maker 0.4.3."""


def install_background_image_patch():
    """Install background-image and single-frame decoder compatibility fixes.

    The upstream DetectionInputProcessor.resize_and_crop_boxes implementation
    uses ``tf.gather_nd`` after ``tf.where``. TensorFlow 2.8 raises when both
    the box tensor and indices are empty. ``tf.boolean_mask`` preserves the
    same non-zero-area filtering for positive examples and returns valid empty
    tensors for background-only examples.

    Two source images have JPEG filenames but GIF byte signatures. The upstream
    generic decoder expands their animation frames to rank four. Disabling
    animation expansion gives the same single-frame semantics used by every
    other training image without changing the retained source or TFRecords.
    """
    import tensorflow as tf
    from tensorflow_examples.lite.model_maker.third_party.efficientdet import (
        dataloader,
    )
    from tensorflow_examples.lite.model_maker.third_party.efficientdet.object_detection import (
        tf_example_decoder,
    )

    def decode_single_frame(self, parsed_tensors):
        del self
        image = tf.io.decode_image(
            parsed_tensors["image/encoded"],
            channels=3,
            expand_animations=False,
        )
        image.set_shape([None, None, 3])
        return image

    def background_safe_resize_and_crop_boxes(processor):
        boxlist = dataloader.preprocessor.box_list.BoxList(processor._boxes)
        boxes = dataloader.preprocessor.box_list_scale(
            boxlist, processor._scaled_height, processor._scaled_width
        ).get()
        box_offset = tf.stack(
            [
                processor._crop_offset_y,
                processor._crop_offset_x,
                processor._crop_offset_y,
                processor._crop_offset_x,
            ]
        )
        boxes -= tf.cast(tf.reshape(box_offset, [1, 4]), tf.float32)
        boxes = processor.clip_boxes(boxes)

        def empty_result():
            return boxes[:0], processor._classes[:0]

        def filtered_result():
            valid = tf.not_equal(
                (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]), 0
            )
            return (
                tf.boolean_mask(boxes, valid),
                tf.boolean_mask(processor._classes, valid),
            )

        instance_count = tf.minimum(
            tf.shape(boxes)[0], tf.shape(processor._classes)[0]
        )
        return tf.cond(
            tf.equal(instance_count, 0), empty_result, filtered_result
        )

    dataloader.DetectionInputProcessor.resize_and_crop_boxes = (
        background_safe_resize_and_crop_boxes
    )
    tf_example_decoder.TfExampleDecoder._decode_image = decode_single_frame
