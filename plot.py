import os
import json
from datetime import datetime, timedelta
import webbrowser

import storage


def _build_active_block_record(seconds_list, block_duration, period_count, blocks_per_period):
    active_block_record = [[0 for _ in range(blocks_per_period)] for _ in range(period_count)]
    seconds_per_period = block_duration * blocks_per_period
    for seconds_since_midnight in seconds_list:
        period_index = seconds_since_midnight // seconds_per_period
        block_index = (seconds_since_midnight % seconds_per_period) // block_duration
        if 0 <= period_index < period_count and 0 <= block_index < blocks_per_period:
            active_block_record[period_index][block_index] = 1
    return active_block_record


def calculate_daily_work_hours(seconds_list):
    active_block_record = _build_active_block_record(seconds_list, block_duration=36, period_count=24, blocks_per_period=100)
    activities_per_hour = [sum(x) / 100.0 for x in active_block_record]
    return round(sum(activities_per_hour), 1)


def calculate_hourly_percent(seconds_list):
    active_block_record = _build_active_block_record(seconds_list, block_duration=36, period_count=24, blocks_per_period=100)
    return [int(sum(x)) for x in active_block_record]


def get_last_several_days_activities(num_days):
    start_of_last_several_days = datetime.now().date() - timedelta(days=num_days - 1)
    last_several_days_date = []
    last_several_days_activities_daily = []
    day_seconds_map = {}
    for i in range(num_days):
        current_date = start_of_last_several_days + timedelta(days=i)
        day_key = current_date.strftime("%Y-%m-%d")
        seconds_list = storage.get_activity_seconds_for_date(current_date)
        day_seconds_map[day_key] = seconds_list
        last_several_days_date.append(current_date.strftime("%m-%d"))
        last_several_days_activities_daily.append(calculate_daily_work_hours(seconds_list) if seconds_list else 0)
    return last_several_days_date, last_several_days_activities_daily, day_seconds_map


def plot_fig():
    week_number = 24
    today_date = datetime.today().date()

    num_days = (week_number - 1) * 7 + datetime.today().weekday() + 1
    last_several_days_data, last_several_days_activities_daily, day_seconds_map = get_last_several_days_activities(num_days)

    for i in range(num_days, week_number * 7):
        last_several_days_activities_daily.append(-1)

    start_date = datetime.now().date() - timedelta(days=num_days - 1)
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
            day_key = cell_date.strftime("%Y-%m-%d")
            hourly_percent = calculate_hourly_percent(day_seconds_map.get(day_key, []))
            heatmap_data.append(
                [week_index, day_index, value, hourly_percent, cell_date.strftime("%Y-%m-%d"), ylabels[cell_date.weekday()]]
            )

    trend_days = min(30, len(last_several_days_data))
    trend_labels = last_several_days_data[-trend_days:]
    trend_values = last_several_days_activities_daily[:num_days][-trend_days:]
    trend_dates = [(today_date - timedelta(days=trend_days - 1 - i)).strftime("%Y-%m-%d") for i in range(trend_days)]
    trend_weekdays = [ylabels[(today_date - timedelta(days=trend_days - 1 - i)).weekday()] for i in range(trend_days)]
    trend_max = max(trend_values, default=0)
    trend_y_max = max(9, int(trend_max) + 1)
    trend_total = round(sum(trend_values), 1)
    recorded_values = [value for value in last_several_days_activities_daily[:num_days] if value is not None and value >= 0]
    active_days_count = len([value for value in recorded_values if value > 0])
    average_daily_work = round(sum(recorded_values) / len(recorded_values), 1) if recorded_values else 0
    peak_daily_work = round(max(recorded_values), 1) if recorded_values else 0
    current_local_date_str = today_date.strftime("%Y-%m-%d")
    current_local_hour = datetime.now().hour

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Work Intensity</title>
  <style>
    html, body {{ height: 100%; margin: 0; font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Helvetica Neue', Arial, sans-serif; background: linear-gradient(180deg, #f8fafc 0%, #f3f4f6 100%); color: #111827; }}
    .container {{ height: 100%; display: grid; grid-template-rows: 2fr 1fr; gap: 14px; padding: 14px; box-sizing: border-box; }}
    .panel {{ border: 1px solid rgba(226, 232, 240, 0.9); border-radius: 16px; padding: 14px; box-sizing: border-box; background: rgba(255, 255, 255, 0.9); box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06); backdrop-filter: blur(6px); }}
    .title {{ font-size: 18px; font-weight: 700; margin: 0; letter-spacing: -0.01em; }}
    .subtitle {{ font-size: 12px; color: #6b7280; margin: 4px 0 0 0; }}
    .top {{ display: grid; grid-template-rows: auto 1fr auto; gap: 10px; height: 100%; }}
    .bottom {{ display: grid; grid-template-rows: auto 1fr; gap: 8px; height: 100%; }}
    .section-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
    .metrics {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
    .metric {{ min-width: 86px; padding: 8px 10px; border-radius: 12px; background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%); border: 1px solid rgba(199, 210, 254, 0.7); }}
    .metric-label {{ font-size: 11px; color: #6b7280; margin-bottom: 4px; }}
    .metric-value {{ font-size: 16px; font-weight: 700; color: #111827; }}
    #contrib {{ width: 100%; height: 100%; }}
    #bars {{ width: 100%; height: 100%; }}
    .legend {{ display: flex; justify-content: space-between; align-items: center; gap: 12px; color: #6b7280; font-size: 12px; }}
    .legend-scale {{ display: flex; align-items: center; gap: 6px; }}
    .legend-note {{ color: #9ca3af; }}
    .legend .box {{ width: 12px; height: 12px; border-radius: 4px; border: 1px solid rgba(27, 31, 35, 0.04); }}
  </style>
</head>
<body>
  <div class="container">
    <div class="panel">
      <div class="top">
        <div class="section-head">
          <div>
            <p class="title">最近 {week_number} 周工作时长</p>
            <p class="subtitle">按天展示近半年活跃时长分布，颜色越深表示当天越活跃。</p>
          </div>
          <div class="metrics">
            <div class="metric">
              <div class="metric-label">活跃天数</div>
              <div class="metric-value">{active_days_count}</div>
            </div>
            <div class="metric">
              <div class="metric-label">日均时长</div>
              <div class="metric-value">{average_daily_work}h</div>
            </div>
            <div class="metric">
              <div class="metric-label">单日峰值</div>
              <div class="metric-value">{peak_daily_work}h</div>
            </div>
          </div>
        </div>
        <div id="contrib"></div>
        <div class="legend">
          <span class="legend-note">工作时长热力分布</span>
          <div class="legend-scale">
            <span>少</span>
            <span class="box" style="background:#eef2f7"></span>
            <span class="box" style="background:#c7f0cf"></span>
            <span class="box" style="background:#7dd87f"></span>
            <span class="box" style="background:#34b45f"></span>
            <span class="box" style="background:#157f3b"></span>
            <span>多</span>
          </div>
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

    const contribBaseOption = {{
      tooltip: {{
        position: 'top',
        confine: true,
        backgroundColor: 'rgba(255, 255, 255, 0.98)',
        borderColor: '#dbe4ee',
        borderWidth: 1,
        extraCssText: 'box-shadow: 0 18px 36px rgba(15,23,42,0.12); padding: 12px; border-radius: 14px;',
        formatter: (p) => {{
          const date = p.data && p.data.date ? p.data.date : '';
          const weekday = p.data && p.data.weekday ? p.data.weekday : '';
          const hourly = p.data && p.data.hourly ? p.data.hourly : [];
          const value = p.value && p.value.length ? p.value[2] : 0;
          const svg = hourlySparklineSvg(hourly, date);
          return `<div style="min-width: 580px;">
            <div style="display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom: 8px;">
              <div style="font-size: 14px; font-weight: 700;">${{date}} ${{weekday}}</div>
              <div style="font-size: 18px; font-weight: 800; color: #166534;">${{value}}h</div>
            </div>
            <div style="margin-bottom: 6px;">${{svg}}</div>
            <div style="font-size: 12px; color: #6b7280;">活跃度趋势（10:00-24:00）</div>
          </div>`;
        }}
      }},
      xAxis: {{
        type: 'category',
        data: weeks,
        position: 'top',
        axisTick: {{ show: false }},
        axisLine: {{ show: false }},
        splitLine: {{ show: false }},
        axisLabel: {{
          interval: 0,
          fontSize: 14,
          fontWeight: 600,
          color: '#6b7280',
          margin: 10,
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
          fontSize: 13,
          fontWeight: 600,
          color: '#6b7280',
          interval: 0,
          margin: 12
        }}
      }},
      visualMap: {{
        type: 'piecewise',
        show: false,
        pieces: [
          {{ lte: 0, color: '#f3f6f9' }},
          {{ gt: 0, lte: 2, color: '#dceddf' }},
          {{ gt: 2, lte: 4, color: '#b5ddbf' }},
          {{ gt: 4, lte: 6, color: '#7fc397' }},
          {{ gt: 6, color: '#4f9d72' }},
        ]
      }},
      series: [{{
        type: 'heatmap',
        data: heatmapData,
        label: {{
          show: true,
          fontSize: 12,
          fontWeight: 700,
          formatter: (p) => {{
            const v = p.value && p.value.length ? p.value[2] : null;
            if (v === null || v === undefined || v <= 0) return '';
            const text = `${{v}}h`;
            if (v <= 2) return `{{soft|${{text}}}}`;
            if (v <= 4) return `{{mid|${{text}}}}`;
            return `{{light|${{text}}}}`;
          }},
          rich: {{
            soft: {{
              color: '#4b5563',
              fontSize: 12,
              fontWeight: 700
            }},
            mid: {{
              color: '#1f2937',
              fontSize: 12,
              fontWeight: 700
            }},
            light: {{
              color: 'rgba(255,255,255,0.92)',
              fontSize: 12,
              fontWeight: 700,
              textShadowColor: 'rgba(15, 23, 42, 0.18)',
              textShadowBlur: 6
            }}
          }}
        }},
        itemStyle: {{
          borderWidth: 3,
          borderColor: 'rgba(255,255,255,0.95)',
          borderRadius: 7,
          shadowBlur: 0,
          shadowColor: 'rgba(15, 23, 42, 0.08)'
        }},
        emphasis: {{
          itemStyle: {{
            borderColor: '#0f172a',
            borderWidth: 2,
            shadowBlur: 18,
            shadowColor: 'rgba(15, 23, 42, 0.18)'
          }}
        }}
      }}]
    }};

    function renderContribChart() {{
      const width = contribEl.clientWidth || 960;
      const height = contribEl.clientHeight || 420;
      const leftPadding = 64;
      const rightPadding = 18;
      const topPadding = 40;
      const bottomPadding = 20;
      const plotMaxWidth = Math.max(0, width - leftPadding - rightPadding);
      const plotMaxHeight = Math.max(0, height - topPadding - bottomPadding);
      const cellSize = Math.max(10, Math.floor(Math.min(plotMaxWidth / weeks.length, plotMaxHeight / ylabels.length)));
      const gridWidth = cellSize * weeks.length;
      const gridHeight = cellSize * ylabels.length;
      const gridLeft = leftPadding + Math.max(0, Math.floor((plotMaxWidth - gridWidth) / 2));
      const gridTop = topPadding + Math.max(0, Math.floor((plotMaxHeight - gridHeight) / 2));
      contribChart.setOption({{
        ...contribBaseOption,
        grid: {{
          left: gridLeft,
          top: gridTop,
          width: gridWidth,
          height: gridHeight,
          containLabel: false
        }}
      }});
    }}

    renderContribChart();

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
      renderContribChart();
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
