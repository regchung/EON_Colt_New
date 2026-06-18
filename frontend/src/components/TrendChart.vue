<script setup>
// 零依賴的多序列 SVG 折線趨勢圖(RWD:viewBox + 100% 寬)。
import { computed } from 'vue'

const props = defineProps({
  labels: { type: Array, default: () => [] },          // x 軸標籤(字串)
  series: { type: Array, default: () => [] },           // [{ name, color, values:[number], dashed?:bool }]
  height: { type: Number, default: 220 },
  unit: { type: String, default: '' },                  // y 值單位(顯示於 tooltip)
  maxXLabels: { type: Number, default: 8 },             // x 軸最多顯示幾個標籤
})

const W = 760
const PAD = { t: 12, r: 12, b: 26, l: 40 }

const maxV = computed(() => {
  const all = props.series.flatMap((s) => s.values || [])
  return Math.max(1, ...all)
})
const n = computed(() => props.labels.length)

function x(i) {
  if (n.value <= 1) return PAD.l
  return PAD.l + (i * (W - PAD.l - PAD.r)) / (n.value - 1)
}
function y(v) {
  const h = props.height - PAD.t - PAD.b
  return PAD.t + h - (v / maxV.value) * h
}

const points = computed(() =>
  props.series.map((s) => ({
    ...s,
    path: (s.values || []).map((v, i) => `${x(i)},${y(v)}`).join(' '),
    dots: (s.values || []).map((v, i) => ({ cx: x(i), cy: y(v), v })),
  }))
)

// y 軸刻度(0、中、max)
const yTicks = computed(() => {
  const m = maxV.value
  return [0, Math.round(m / 2), m].map((v) => ({ v, y: y(v) }))
})

// x 軸標籤(等距抽樣,避免擁擠)
const xTicks = computed(() => {
  const step = Math.max(1, Math.ceil(n.value / props.maxXLabels))
  const out = []
  for (let i = 0; i < n.value; i += step) out.push({ i, x: x(i), label: props.labels[i] })
  if (n.value && out[out.length - 1]?.i !== n.value - 1)
    out.push({ i: n.value - 1, x: x(n.value - 1), label: props.labels[n.value - 1] })
  return out
})
</script>

<template>
  <div>
    <svg :viewBox="`0 0 ${W} ${height}`" preserveAspectRatio="none"
         style="width:100%;" :style="{ height: height + 'px' }" role="img">
      <!-- y 格線 + 刻度 -->
      <g v-for="t in yTicks" :key="'y' + t.v">
        <line :x1="PAD.l" :y1="t.y" :x2="W - PAD.r" :y2="t.y" stroke="#e9ecef" stroke-width="1" />
        <text :x="PAD.l - 6" :y="t.y + 4" text-anchor="end" font-size="11" fill="#868e96">{{ t.v }}</text>
      </g>
      <!-- x 刻度標籤 -->
      <g v-for="t in xTicks" :key="'x' + t.i">
        <text :x="t.x" :y="height - 8" text-anchor="middle" font-size="10" fill="#868e96">{{ t.label }}</text>
      </g>
      <!-- 折線 + 點 -->
      <g v-for="s in points" :key="s.name">
        <polyline :points="s.path" fill="none" :stroke="s.color" stroke-width="2"
                  :stroke-dasharray="s.dashed ? '5 4' : '0'" stroke-linejoin="round" stroke-linecap="round" />
        <circle v-for="(d, i) in s.dots" :key="i" :cx="d.cx" :cy="d.cy" r="2.5" :fill="s.color">
          <title>{{ labels[i] }}　{{ s.name }}：{{ d.v }}{{ unit }}</title>
        </circle>
      </g>
    </svg>
    <!-- 圖例 -->
    <div class="d-flex flex-wrap gap-3 mt-1">
      <span v-for="s in series" :key="s.name" class="small text-muted d-inline-flex align-items-center">
        <span class="me-1" :style="{ display: 'inline-block', width: '14px', height: '0', borderTop: `3px ${s.dashed ? 'dashed' : 'solid'} ${s.color}` }"></span>
        {{ s.name }}
      </span>
    </div>
  </div>
</template>
