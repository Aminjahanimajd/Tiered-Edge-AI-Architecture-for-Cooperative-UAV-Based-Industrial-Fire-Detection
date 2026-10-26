#!/usr/bin/env python3
"""Run TF Object Detection model_main_tf2 with TF 2.15/tf-slim compatibility."""

import tensorflow as tf
from tensorflow.python.ops import control_flow_ops


# tf-slim 1.1 imports this historical private symbol. TensorFlow 2.15 removed
# the alias while retaining the equivalent public operation.
if not hasattr(control_flow_ops, "case"):
    control_flow_ops.case = tf.case
if not hasattr(control_flow_ops, "cond"):
    control_flow_ops.cond = tf.cond


def install_single_frame_decoder():
    """Select frame zero for mislabeled multi-frame images in TFRecords.

    The frozen dataset contains two JPEG-named files with GIF byte signatures.
    Ultralytics consumes one image frame, while tf-slim's generic decoder
    returns every GIF frame and creates a rank-5 batch. Selecting frame zero
    preserves the raw evidence and aligns the TensorFlow view with the
    single-frame detector comparison.
    """
    from tf_slim.data import tfexample_decoder

    def decode_first_frame(self, image_buffer, image_format):
        def decode_image():
            return tf.cast(
                tf.io.decode_image(
                    image_buffer,
                    channels=self._channels,
                    expand_animations=False,
                ),
                self._dtype,
            )

        def decode_jpeg():
            return tf.cast(
                tf.io.decode_jpeg(
                    image_buffer,
                    channels=self._channels,
                    dct_method=self._dct_method,
                ),
                self._dtype,
            )

        def decode_encoded():
            return tf.cond(tf.io.is_jpeg(image_buffer), decode_jpeg, decode_image)

        image = tf.case(
            [
                (
                    tf.logical_or(
                        tf.equal(image_format, "raw"),
                        tf.equal(image_format, "RAW"),
                    ),
                    lambda: tf.io.decode_raw(image_buffer, out_type=self._dtype),
                )
            ],
            default=decode_encoded,
            exclusive=True,
        )
        image.set_shape([None, None, 3])
        if self._shape is not None:
            image = tf.reshape(image, self._shape)
        return image

    tfexample_decoder.Image._decode = decode_first_frame


install_single_frame_decoder()


from object_detection import model_main_tf2  # noqa: E402


if __name__ == "__main__":
    tf.compat.v1.app.run(model_main_tf2.main)
