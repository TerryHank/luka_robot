#!/usr/bin/env python3

import argparse

from rknn.api import RKNN


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_onnx")
    parser.add_argument("output_rknn")
    args = parser.parse_args()

    rknn = RKNN(verbose=True)
    try:
        ret = rknn.config(
            mean_values=[[0, 0, 0]],
            std_values=[[255, 255, 255]],
            target_platform="rk3588",
        )
        if ret != 0:
            return ret
        ret = rknn.load_onnx(model=args.input_onnx)
        if ret != 0:
            return ret
        ret = rknn.build(do_quantization=False)
        if ret != 0:
            return ret
        return rknn.export_rknn(args.output_rknn)
    finally:
        rknn.release()


if __name__ == "__main__":
    raise SystemExit(main())
