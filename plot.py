import re
import time
from datetime import datetime, timedelta

import matplotlib.pyplot as plt

# 定义正则表达式模式，用于匹配时间戳
timestamp_pattern = r"\[(\d{2}:\d{2}:\d{2})\]"


# 读取日志文件并解析时间戳
def parse_log_file(file_path):
    active_block_record = [[0 for _ in range(100)] for _ in range(48)]  # 初始化每个统计周期的活跃块数列表
    block_duration = 18  # 每个统计块的时长
    blocks_per_period = 100  # 每个统计周期的块数
    time_format = "%H:%M:%S"  # 时间戳的格式

    with open(file_path, "r") as file:
        for line in file:
            match = re.search(timestamp_pattern, line)
            if match:
                timestamp_str = match.group(1)
                timestamp = datetime.strptime(timestamp_str, time_format)
                # 计算时间戳距离当天零点的秒数
                seconds_since_midnight = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
                # 计算所属统计周期的索引
                period_index = seconds_since_midnight // (block_duration * blocks_per_period)
                block_index = seconds_since_midnight % (block_duration * blocks_per_period) // block_duration
                active_block_record[period_index][block_index] = 1

    active_block_counts = [sum(x) for x in active_block_record]
    return active_block_counts


# 绘制柱状图
def plot_activity(active_block_counts):
    x_labels = [
        "00:00-00:30",
        "00:30-01:00",
        "01:00-01:30",
        "01:30-02:00",
        "02:00-02:30",
        "02:30-03:00",
        "03:00-03:30",
        "03:30-04:00",
        "04:00-04:30",
        "04:30-05:00",
        "05:00-05:30",
        "05:30-06:00",
        "06:00-06:30",
        "06:30-07:00",
        "07:00-07:30",
        "07:30-08:00",
        "08:00-08:30",
        "08:30-09:00",
        "09:00-09:30",
        "09:30-10:00",
        "10:00-10:30",
        "10:30-11:00",
        "11:00-11:30",
        "11:30-12:00",
        "12:00-12:30",
        "12:30-13:00",
        "13:00-13:30",
        "13:30-14:00",
        "14:00-14:30",
        "14:30-15:00",
        "15:00-15:30",
        "15:30-16:00",
        "16:00-16:30",
        "16:30-17:00",
        "17:00-17:30",
        "17:30-18:00",
        "18:00-18:30",
        "18:30-19:00",
        "19:00-19:30",
        "19:30-20:00",
        "20:00-20:30",
        "20:30-21:00",
        "21:00-21:30",
        "21:30-22:00",
        "22:00-22:30",
        "22:30-23:00",
        "23:00-23:30",
        "23:30-00:00",
    ]
    x = range(len(active_block_counts))

    plt.figure(figsize=(15, 5))
    plt.title("Work Intensity")
    plt.subplots_adjust(bottom=0.2)  # 调整横坐标标签的纵向显示空间

    plt.bar(x, active_block_counts, tick_label=x_labels)
    plt.xticks(rotation=90)
    plt.yticks(range(0, 101, 10))
    plt.ylim(0, 100)  # 设置纵轴的范围为0到100
    plt.show()


def plot_fig(log_file_path):
    active_periods = parse_log_file(log_file_path)
    plot_activity(active_periods)


if __name__ == "__main__":
    log_file_path = f'log/{time.strftime("%Y-%m-%d")}.log'
    plot_fig(active_periods)
