#
# https://github.com/bornfree/dive-color-corrector/tree/main
#

import os

import numpy as np
import cv2
import math


class ColorCorrectionClass:
    def __init__(self, source_path, output_path):
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"Source path does not exist: {source_path}")


        self.source_path = source_path
        self.output_path = output_path
        self.sample_seconds = 2
        self.min_avg_red = 60
        self.max_hue_shift = 120
        self.threshold_ratio = 2000
        self.blue_magic_value = 1.2


        self.mat = None

    def correct_image(self):
        self.mat = cv2.imread(self.source_path)
        self.mat = cv2.cvtColor(self.mat, cv2.COLOR_BGR2RGB)

        original_mat = self.mat.copy()

        filter_matrix = self.get_filter_matrix()

        corrected_mat = self.apply_filter(original_mat, filter_matrix)
        corrected_mat = cv2.cvtColor(corrected_mat, cv2.COLOR_RGB2BGR)

        cv2.imwrite(self.output_path, corrected_mat)


    def hue_shift_red(self, mat, h):
        U = math.cos(h * math.pi / 180)
        W = math.sin(h * math.pi / 180)

        r = (0.299 + 0.701 * U + 0.168 * W) * mat[..., 0]
        g = (0.587 - 0.587 * U + 0.330 * W) * mat[..., 1]
        b = (0.114 - 0.114 * U - 0.497 * W) * mat[..., 2]

        return np.dstack([r, g, b])


    def normalizing_interval(self, array):
        high = 255
        low = 0
        max_dist = 0

        for i in range(1, len(array)):
            dist = array[i] - array[i - 1]
            if (dist > max_dist):
                max_dist = dist
                high = array[i]
                low = array[i - 1]

        return (low, high)


    def apply_filter(self, mat, filt):
        r = mat[..., 0]
        g = mat[..., 1]
        b = mat[..., 2]

        r = r * filt[0] + g * filt[1] + b * filt[2] + filt[4] * 255
        g = g * filt[6] + filt[9] * 255
        b = b * filt[12] + filt[14] * 255

        filtered_mat = np.dstack([r, g, b])
        filtered_mat = np.clip(filtered_mat, 0, 255).astype(np.uint8)

        return filtered_mat


    def get_filter_matrix(self):
        mat = cv2.resize(self.mat, (256, 256))

        # Get average values of RGB
        avg_mat = np.array(cv2.mean(mat)[:3], dtype=np.uint8)

        # Find hue shift so that average red reaches MIN_AVG_RED
        new_avg_r = avg_mat[0]
        hue_shift = 0
        while new_avg_r < self.min_avg_red:

            shifted = self.hue_shift_red(avg_mat, hue_shift)
            new_avg_r = np.sum(shifted)
            hue_shift += 1
            if hue_shift > self.max_hue_shift:
                new_avg_r = self.min_avg_red

        # Apply hue shift to whole image and replace red channel
        shifted_mat = self.hue_shift_red(mat, hue_shift)
        new_r_channel = np.sum(shifted_mat, axis=2)
        new_r_channel = np.clip(new_r_channel, 0, 255)
        mat[..., 0] = new_r_channel

        # Get histogram of all channels
        hist_r = hist = cv2.calcHist([mat], [0], None, [256], [0, 256])
        hist_g = hist = cv2.calcHist([mat], [1], None, [256], [0, 256])
        hist_b = hist = cv2.calcHist([mat], [2], None, [256], [0, 256])

        normalize_mat = np.zeros((256, 3))
        threshold_level = (mat.shape[0] * mat.shape[1]) / self.threshold_ratio
        for x in range(256):

            if hist_r[x] < threshold_level:
                normalize_mat[x][0] = x

            if hist_g[x] < threshold_level:
                normalize_mat[x][1] = x

            if hist_b[x] < threshold_level:
                normalize_mat[x][2] = x

        normalize_mat[255][0] = 255
        normalize_mat[255][1] = 255
        normalize_mat[255][2] = 255

        adjust_r_low, adjust_r_high = self.normalizing_interval(normalize_mat[..., 0])
        adjust_g_low, adjust_g_high = self.normalizing_interval(normalize_mat[..., 1])
        adjust_b_low, adjust_b_high = self.normalizing_interval(normalize_mat[..., 2])

        shifted = self.hue_shift_red(np.array([1, 1, 1]), hue_shift)
        shifted_r, shifted_g, shifted_b = shifted[0][0]

        red_gain = 256 / (adjust_r_high - adjust_r_low)
        green_gain = 256 / (adjust_g_high - adjust_g_low)
        blue_gain = 256 / (adjust_b_high - adjust_b_low)

        redOffset = (-adjust_r_low / 256) * red_gain
        greenOffset = (-adjust_g_low / 256) * green_gain
        blueOffset = (-adjust_b_low / 256) * blue_gain

        adjust_red = shifted_r * red_gain
        adjust_red_green = shifted_g * red_gain
        adjust_red_blue = shifted_b * red_gain * self.blue_magic_value

        return np.array([
            adjust_red, adjust_red_green, adjust_red_blue, 0, redOffset,
            0, green_gain, 0, 0, greenOffset,
            0, 0, blue_gain, 0, blueOffset,
            0, 0, 0, 1, 0,
        ])

    def correct_video(self):
        try:
            video_data = None
            for item in self.analyze_video():

                if type(item) == dict:
                    video_data = item

            # Original
            # [x for x in self.process_video(video_data, yield_preview=False)]

            list(self.process_video(video_data, yield_preview=False))

        except Exception as e:
            print(f"Error during video processing: {e}: {self.source_path}")
            raise e

    def analyze_video(self):
        # Initialize new video writer
        cap = cv2.VideoCapture(self.source_path)
        fps = math.ceil(cap.get(cv2.CAP_PROP_FPS))
        frame_count = math.ceil(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Get filter matrices for every 10th frame
        filter_matrix_indexes = []
        filter_matrices = []
        count = 0

        print("Analyzing...")
        while cap.isOpened():

            count += 1
            print(f"{count} frames", end="\r")
            ret, frame = cap.read()
            if not ret:
                # End video read if we have gone beyond reported frame count
                if count >= frame_count:
                    break

                # Failsafe to prevent an infinite loop
                if count >= 1e6:
                    break

                # Otherwise this is just a faulty frame read, try reading next frame
                continue

            # Pick filter matrix from every N seconds
            if count % (fps * self.sample_seconds) == 0:
                self.mat = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                filter_matrix_indexes.append(count)
                filter_matrices.append(self.get_filter_matrix())

            yield count

        cap.release()

        # Build a interpolation function to get filter matrix at any given frame
        filter_matrices = np.array(filter_matrices)

        yield {
            "input_video_path": self.source_path,
            "output_video_path": self.output_path,
            "fps": fps,
            "frame_count": count,
            "filters": filter_matrices,
            "filter_indices": filter_matrix_indexes
        }


    def process_video(self, video_data, yield_preview=False):

        try:
            cap = cv2.VideoCapture(video_data["input_video_path"])

            frame_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            frame_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            new_video = cv2.VideoWriter(video_data["output_video_path"], fourcc, video_data["fps"],
                                        (int(frame_width), int(frame_height)))

            filter_matrices = video_data["filters"]
            filter_indices = video_data["filter_indices"]

            filter_matrix_size = len(filter_matrices[0])

            def get_interpolated_filter_matrix(frame_number):

                return [np.interp(frame_number, filter_indices, filter_matrices[..., x]) for x in range(filter_matrix_size)]

            print("Processing...")

            frame_count = video_data["frame_count"]

            count = 0
            cap = cv2.VideoCapture(video_data["input_video_path"])
            while cap.isOpened():

                count += 1
                percent = 100 * count / frame_count
                print("{:.2f}".format(percent), end=" % \r")
                ret, frame = cap.read()

                if not ret:
                    # End video read if we have gone beyond reported frame count
                    if count >= frame_count:
                        break

                    # Failsafe to prevent an infinite loop
                    if count >= 1e6:
                        break

                    # Otherwise this is just a faulty frame read, try reading next
                    continue

                # Apply the filter
                rgb_mat = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                interpolated_filter_matrix = get_interpolated_filter_matrix(count)
                corrected_mat = self.apply_filter(rgb_mat, interpolated_filter_matrix)
                corrected_mat = cv2.cvtColor(corrected_mat, cv2.COLOR_RGB2BGR)

                new_video.write(corrected_mat)

                if yield_preview:
                    preview = frame.copy()
                    width = preview.shape[1] // 2
                    height = preview.shape[0] // 2
                    preview[::, width:] = corrected_mat[::, width:]

                    preview = cv2.resize(preview, (width, height))

                    yield percent, cv2.imencode('.png', preview)[1].tobytes()
                else:
                    yield None

            cap.release()
            new_video.release()

        except Exception as e:
            print(f"Error during video processing: {e}")
            raise e

