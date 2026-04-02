import os
import json
import re
from datetime import datetime, timedelta
import pickle
import webbrowser


timestamp_pattern = r"\[(\d{2}:\d{2}:\d{2})\]"


def parse_log_file(file_path):
    active_block_record = [[0 for _ in range(100)] for _ in range(24)]
    block_duration = 36
    blocks_per_period = 100
    time_format = "%H:%M:%S"

    with open(file_path, "r") as file:
        for line in file:
            match = re.search(timestamp_pattern, line)
            if match:
                timestamp_str = match.group(1)
                timestamp = datetime.strptime(timestamp_str, time_format)
                seconds_since_midnight = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
                period_index = seconds_since_midnight // (block_duration * blocks_per_period)
                block_index = seconds_since_midnight % (block_duration * blocks_per_period) // block_duration
                if 0 <= period_index < 24 and 0 <= block_index < blocks_per_period:
                    active_block_record[period_index][block_index] = 1

    activities_per_hour = [sum(x) / 100.0 for x in active_block_record]
    work_intensity_daily = round(sum(activities_per_hour), 1)
    return work_intensity_daily


def parse_log_file_hourly_percent(file_path):
    active_block_record = [[0 for _ in range(100)] for _ in range(24)]
    block_duration = 36
    blocks_per_period = 100
    time_format = "%H:%M:%S"

    with open(file_path, "r") as file:
        for line in file:
            match = re.search(timestamp_pattern, line)
            if not match:
                continue
            timestamp_str = match.group(1)
            timestamp = datetime.strptime(timestamp_str, time_format)
            seconds_since_midnight = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
            period_index = seconds_since_midnight // (block_duration * blocks_per_period)
            block_index = seconds_since_midnight % (block_duration * blocks_per_period) // block_duration
            if 0 <= period_index < 24 and 0 <= block_index < blocks_per_period:
                active_block_record[period_index][block_index] = 1

    return [int(sum(x)) for x in active_block_record]


PER_HALF_HOUR_LABELS = [
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


def parse_log_file_half_hour_percent(file_path):
    block_duration = 18
    blocks_per_period = 100
    seconds_per_period = block_duration * blocks_per_period
    period_count = 48
    time_format = "%H:%M:%S"
    active_block_record = [[0 for _ in range(blocks_per_period)] for _ in range(period_count)]

    with open(file_path, "r") as file:
        for line in file:
            match = re.search(timestamp_pattern, line)
            if not match:
                continue
            timestamp_str = match.group(1)
            timestamp = datetime.strptime(timestamp_str, time_format)
            seconds_since_midnight = timestamp.hour * 3600 + timestamp.minute * 60 + timestamp.second
            period_index = seconds_since_midnight // seconds_per_period
            block_index = (seconds_since_midnight % seconds_per_period) // block_duration
            if 0 <= period_index < period_count and 0 <= block_index < blocks_per_period:
                active_block_record[period_index][block_index] = 1

    return [round(sum(x) / blocks_per_period * 100, 1) for x in active_block_record]


def get_last_several_days_activities(num_days):
    today_date = datetime.now().date()
    start_of_last_several_days = datetime.now().date() - timedelta(days=num_days - 1)

    os.makedirs("log", exist_ok=True)

    cache_file_path = os.path.join("log/work_intensity_cache.pkl")
    if os.path.exists(cache_file_path):
        with open(cache_file_path, "rb") as cache_file:
            cache = pickle.load(cache_file)
    else:
        cache = {}

    last_several_days_date = []
    last_several_days_activities_daily = []
    for i in range(num_days):
        date = start_of_last_several_days + timedelta(days=i)

        last_several_days_date.append(date.strftime("%m-%d"))

        log_file_path = f'log/{date.strftime("%Y-%m-%d")}.log'
        if os.path.exists(log_file_path):
            if date == today_date:
                work_intensity_daily = parse_log_file(log_file_path)
            else:
                if log_file_path not in cache:
                    cache[log_file_path] = parse_log_file(log_file_path)
                work_intensity_daily = cache[log_file_path]
            last_several_days_activities_daily.append(work_intensity_daily)
        else:
            last_several_days_activities_daily.append(0)

    # 将结果存入缓存
    with open(cache_file_path, "wb") as cache_file:
        pickle.dump(cache, cache_file)

    return last_several_days_date, last_several_days_activities_daily


def plot_fig():
    week_number = 24
    today_date = datetime.today().date()

    num_days = (week_number - 1) * 7 + datetime.today().weekday() + 1
    last_several_days_data, last_several_days_activities_daily = get_last_several_days_activities(num_days)

    for i in range(num_days, week_number * 7):
        last_several_days_activities_daily.append(-1)

    start_date = datetime.now().date() - timedelta(days=num_days - 1)
    hourly_cache_file_path = os.path.join("log/work_intensity_hourly_cache.pkl")
    if os.path.exists(hourly_cache_file_path):
        with open(hourly_cache_file_path, "rb") as cache_file:
            hourly_cache = pickle.load(cache_file)
    else:
        hourly_cache = {}

    xlabels = []
    for i in range(week_number - 1):
        start_label = last_several_days_data[i * 7]
        end_label = last_several_days_data[i * 7 + 6]
        xlabels.append(f"{start_label} - {end_label}")
    xlabels.append(
        f'{last_several_days_data[(week_number - 1) * 7]} - {(datetime.today() + timedelta(7 - datetime.today().weekday() - 1)).strftime("%m-%d")}'
    )

    ylabels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    heatmap_data = []
    for week_index in range(week_number):
        for day_index in range(7):
            value = last_several_days_activities_daily[week_index * 7 + day_index]
            if value is None or value < 0:
                continue
            cell_date = start_date + timedelta(days=week_index * 7 + day_index)
            log_file_path = f'log/{cell_date.strftime("%Y-%m-%d")}.log'
            if os.path.exists(log_file_path):
                if cell_date == today_date:
                    hourly_percent = parse_log_file_hourly_percent(log_file_path)
                    hourly_cache[log_file_path] = hourly_percent
                else:
                    if log_file_path not in hourly_cache:
                        hourly_cache[log_file_path] = parse_log_file_hourly_percent(log_file_path)
                    hourly_percent = hourly_cache[log_file_path]
            else:
                hourly_percent = [0 for _ in range(24)]
                if log_file_path in hourly_cache and cell_date == today_date:
                    del hourly_cache[log_file_path]
            heatmap_data.append(
                [week_index, day_index, value, hourly_percent, cell_date.strftime("%Y-%m-%d"), ylabels[cell_date.weekday()]]
            )

    with open(hourly_cache_file_path, "wb") as cache_file:
        pickle.dump(hourly_cache, cache_file)

    trend_days = min(30, len(last_several_days_data))
    trend_labels = last_several_days_data[-trend_days:]
    trend_values = last_several_days_activities_daily[:num_days][-trend_days:]
    trend_dates = [(today_date - timedelta(days=trend_days - 1 - i)).strftime("%Y-%m-%d") for i in range(trend_days)]
    trend_weekdays = [ylabels[(today_date - timedelta(days=trend_days - 1 - i)).weekday()] for i in range(trend_days)]
    trend_max = max(trend_values, default=0)
    trend_y_max = max(9, int(trend_max) + 1)
    trend_total = round(sum(trend_values), 1)
    current_local_date_str = today_date.strftime("%Y-%m-%d")
    current_local_hour = datetime.now().hour

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Work Intensity</title>
  <style>
    html, body {{ height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', Arial, sans-serif; }}
    .container {{ height: 100%; display: grid; grid-template-rows: 2fr 1fr; gap: 12px; padding: 12px; box-sizing: border-box; }}
    .panel {{ border: 1px solid #e5e7eb; border-radius: 10px; padding: 10px; box-sizing: border-box; }}
    .title {{ font-size: 16px; font-weight: 600; margin: 0 0 8px 0; }}
    .top {{ display: grid; grid-template-rows: auto 1fr auto; gap: 6px; height: 100%; }}
    .bottom {{ display: grid; grid-template-rows: auto 1fr; gap: 6px; height: 100%; }}
    #contrib {{ width: 100%; height: 100%; }}
    #bars {{ width: 100%; height: 100%; }}
    .legend {{ display: flex; justify-content: flex-end; align-items: center; gap: 6px; color: #6b7280; font-size: 12px; }}
    .legend .box {{ width: 12px; height: 12px; border-radius: 2px; border: 1px solid rgba(27, 31, 35, 0.06); }}
  </style>
</head>
<body>
  <div class="container">
    <div class="panel">
      <div class="top">
        <p class="title">最近 {week_number} 周工作时长</p>
        <div id="contrib"></div>
        <div class="legend">
          <span>少</span>
          <span class="box" style="background:#ebedf0"></span>
          <span class="box" style="background:#9be9a8"></span>
          <span class="box" style="background:#40c463"></span>
          <span class="box" style="background:#30a14e"></span>
          <span class="box" style="background:#216e39"></span>
          <span>多</span>
        </div>
      </div>
    </div>
    <div class="panel">
      <div class="bottom">
        <p class="title">最近 {trend_days} 天每日工作时长趋势（累计 {trend_total}h）</p>
        <div id="bars"></div>
      </div>
    </div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <script>
    const contribEl = document.getElementById('contrib');
    const barsEl = document.getElementById('bars');
    const contribChart = echarts.init(contribEl);
    const barsChart = echarts.init(barsEl);

    const weekRanges = {json.dumps(xlabels, ensure_ascii=False)};
    const ylabels = {json.dumps(ylabels, ensure_ascii=False)};
    const startDateStr = {json.dumps(start_date.strftime("%Y-%m-%d"), ensure_ascii=False)};
    const startDate = new Date(startDateStr + 'T00:00:00');
    const currentLocalDateStr = {json.dumps(current_local_date_str, ensure_ascii=False)};
    const currentLocalHour = {current_local_hour};
    const heatmapData = {json.dumps(heatmap_data, ensure_ascii=False)}.map((d) => {{
      const x = d[0];
      const y = d[1];
      const v = d[2];
      const hourly = d[3] || [];
      return {{
        value: [x, y, v],
        date: d[4],
        weekday: d[5],
        hourly
      }};
    }});
    const weeks = Array.from({{length: weekRanges.length}}, (_, i) => i);
    const monthLabels = weeks.map((weekIndex) => {{
      const date = new Date(startDate.getTime() + weekIndex * 7 * 24 * 3600 * 1000);
      const month = date.getMonth() + 1;
      return `${{month}}月`;
    }});

    function hourlySparklineSvg(values, dateStr) {{
      const w = 560;
      const h = 190;
      const leftPad = 46;
      const rightPad = 16;
      const topPad = 16;
      const plotH = 120;
      const plotW = w - leftPad - rightPad;
      const maxV = 100;
      const clamp = (n) => Math.max(0, Math.min(maxV, Number(n) || 0));
      const full = (values && values.length ? values : Array.from({{length: 24}}, () => 0));
      const startHour = 10;
      const endHour = 24;
      const visibleEndHour = dateStr === currentLocalDateStr ? Math.min(endHour, currentLocalHour + 1) : endHour;
      const sliced = full.slice(startHour, visibleEndHour);
      const fullIntervalCount = Math.max(1, endHour - startHour);
      const pointPairs = sliced.map((v, i) => {{
        const x = leftPad + ((i + 0.5) / fullIntervalCount) * plotW;
        const y = topPad + (1 - clamp(v) / maxV) * plotH;
        return [x, y];
      }});
      const smoothPath = pointPairs.length <= 1
        ? ''
        : pointPairs.reduce((path, point, index, points) => {{
            const [x, y] = point;
            if (index === 0) {{
              return `M ${{x.toFixed(1)}} ${{y.toFixed(1)}}`;
            }}
            const [prevX, prevY] = points[index - 1];
            const cp1X = prevX + (x - prevX) / 3;
            const cp1Y = prevY;
            const cp2X = x - (x - prevX) / 3;
            const cp2Y = y;
            return `${{path}} C ${{cp1X.toFixed(1)}} ${{cp1Y.toFixed(1)}}, ${{cp2X.toFixed(1)}} ${{cp2Y.toFixed(1)}}, ${{x.toFixed(1)}} ${{y.toFixed(1)}}`;
          }}, '');
      const yTicks = [0, 25, 50, 75, 100].map((t) => {{
        const y = topPad + (1 - t / 100) * plotH;
        return `<g>
          <line x1="${{leftPad}}" y1="${{y}}" x2="${{w - rightPad}}" y2="${{y}}" stroke="#e5e7eb" stroke-width="1" />
          <text x="${{leftPad - 8}}" y="${{y + 4}}" text-anchor="end" font-size="12" fill="#6b7280">${{t}}%</text>
        </g>`;
      }}).join('');
      const xTickHours = Array.from({{length: Math.max(1, endHour - startHour + 1)}}, (_, i) => startHour + i);
      const xTicks = xTickHours.map((t) => {{
        const i = (t - startHour);
        const x = leftPad + (i / fullIntervalCount) * plotW;
        return `<text x="${{x}}" y="${{topPad + plotH + 28}}" text-anchor="middle" font-size="12" fill="#6b7280">${{t === 24 ? '24' : String(t).padStart(2, '0')}}</text>`;
      }}).join('');
      return `<svg width="${{w}}" height="${{h}}" viewBox="0 0 ${{w}} ${{h}}" xmlns="http://www.w3.org/2000/svg">
        <rect x="0" y="0" width="${{w}}" height="${{h}}" rx="8" fill="#ffffff"></rect>
        ${{yTicks}}
        <path d="${{smoothPath}}" fill="none" stroke="#31a354" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <text x="${{w - rightPad}}" y="${{topPad + plotH + 28}}" text-anchor="end" font-size="12" fill="#6b7280"></text>
        ${{xTicks}}
      </svg>`;
    }}

    contribChart.setOption({{
      tooltip: {{
        position: 'top',
        confine: true,
        backgroundColor: 'rgba(255, 255, 255, 0.96)',
        borderColor: '#e5e7eb',
        borderWidth: 1,
        extraCssText: 'box-shadow: 0 10px 20px rgba(0,0,0,0.08); padding: 10px; border-radius: 10px;',
        formatter: (p) => {{
          const date = p.data && p.data.date ? p.data.date : '';
          const weekday = p.data && p.data.weekday ? p.data.weekday : '';
          const hourly = p.data && p.data.hourly ? p.data.hourly : [];
          const svg = hourlySparklineSvg(hourly, date);
          return `<div style="min-width: 580px;">
            <div style="font-size: 14px; font-weight: 600; margin-bottom: 8px;">${{date}} ${{weekday}}</div>
            <div style="margin-bottom: 6px;">${{svg}}</div>
            <div style="font-size: 12px; color: #6b7280;">活跃度趋势（10:00-24:00）</div>
          </div>`;
        }}
      }},
      grid: {{ top: 28, left: 40, right: 10, bottom: 10, containLabel: false }},
      xAxis: {{
        type: 'category',
        data: weeks,
        position: 'top',
        axisTick: {{ show: false }},
        axisLine: {{ show: false }},
        splitLine: {{ show: false }},
        axisLabel: {{
          interval: 0,
          fontSize: 16,
          color: '#6b7280',
          formatter: (value) => {{
            if (value === 0) return monthLabels[0];
            return monthLabels[value] !== monthLabels[value - 1] ? monthLabels[value] : '';
          }}
        }}
      }},
      yAxis: {{
        type: 'category',
        data: ylabels,
        inverse: true,
        axisTick: {{ show: false }},
        axisLine: {{ show: false }},
        splitLine: {{ show: false }},
        axisLabel: {{
          fontSize: 16,
          color: '#6b7280',
          interval: 0
        }}
      }},
      visualMap: {{
        type: 'piecewise',
        show: false,
        pieces: [
          {{ lte: 0, color: '#ebedf0' }},
          {{ gt: 0, lte: 2, color: '#9be9a8' }},
          {{ gt: 2, lte: 4, color: '#40c463' }},
          {{ gt: 4, lte: 6, color: '#30a14e' }},
          {{ gt: 6, color: '#216e39' }},
        ]
      }},
      series: [{{
        type: 'heatmap',
        data: heatmapData,
        label: {{
          show: true,
          fontSize: 14,
          color: '#111827',
          formatter: (p) => {{
            const v = p.value && p.value.length ? p.value[2] : null;
            if (v === null || v === undefined || v <= 0) return '';
            return `${{v}}h`;
          }}
        }},
        itemStyle: {{
          borderWidth: 2,
          borderColor: '#ffffff',
          borderRadius: 2
        }},
        emphasis: {{
          itemStyle: {{
            borderColor: '#111827',
            borderWidth: 1
          }}
        }}
      }}]
    }});

    const trendLabels = {json.dumps(trend_labels, ensure_ascii=False)};
    const trendValues = {json.dumps(trend_values, ensure_ascii=False)};
    const trendDates = {json.dumps(trend_dates, ensure_ascii=False)};
    const trendWeekdays = {json.dumps(trend_weekdays, ensure_ascii=False)};
    const trendSeriesData = trendValues.map((value, index) => ({{
      value,
      date: trendDates[index],
      weekday: trendWeekdays[index]
    }}));

    barsChart.setOption({{
      tooltip: {{
        trigger: 'axis',
        axisPointer: {{
          type: 'line',
          snap: true
        }},
        formatter: (params) => {{
          const item = params && params.length ? params[0] : null;
          if (!item) return '';
          const data = item.data || {{}};
          const date = data.date || trendDates[item.dataIndex] || item.axisValue;
          const weekday = data.weekday || trendWeekdays[item.dataIndex] || '';
          const value = typeof data.value === 'number' ? data.value : item.value;
          return `${{date}} ${{weekday}}<br/>${{value}}h`;
        }}
      }},
      grid: {{ top: 20, left: 50, right: 20, bottom: 50 }},
      xAxis: {{
        type: 'category',
        data: trendLabels,
        boundaryGap: false,
        axisLabel: {{
          interval: Math.max(0, Math.floor(trendLabels.length / 10) - 1),
          fontSize: 12
        }}
      }},
      yAxis: {{
        type: 'value',
        min: 0,
        max: {trend_y_max},
        axisLabel: {{
          formatter: '{{value}}h',
          fontSize: 12
        }},
        splitLine: {{
          lineStyle: {{
            color: '#e5e7eb'
          }}
        }}
      }},
      series: [{{
        type: 'line',
        smooth: true,
        data: trendSeriesData,
        triggerLineEvent: true,
        showSymbol: true,
        symbol: 'circle',
        symbolSize: 8,
        lineStyle: {{ color: '#31a354', width: 3 }},
        itemStyle: {{ color: '#31a354' }},
        emphasis: {{
          focus: 'series',
          scale: true
        }},
        areaStyle: {{
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            {{ offset: 0, color: 'rgba(49, 163, 84, 0.35)' }},
            {{ offset: 1, color: 'rgba(49, 163, 84, 0.05)' }}
          ])
        }}
      }}]
    }});

    window.addEventListener('resize', () => {{
      contribChart.resize();
      barsChart.resize();
    }});
  </script>
</body>
</html>
"""

    os.makedirs("log", exist_ok=True)
    html_path = os.path.abspath(os.path.join("log", "work_intensity.html"))
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    webbrowser.open(f"file://{html_path}")


if __name__ == "__main__":
    plot_fig()
