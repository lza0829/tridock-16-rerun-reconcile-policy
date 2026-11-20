<template>
  <div>
    <div class="hero">
      <div>
        <h1>总览</h1>
        <p>当前到货日三腿行数、折算件数、对账分桶与结案状态。结案后当日预报/实收/回执不可再改，箱规改动也不追溯已封批。</p>
      </div>
      <button @click="load">刷新</button>
    </div>
    <div class="grid" v-if="d">
      <div class="stat"><div class="k">到货日</div><div class="v">{{ d.dock_day }}</div></div>
      <div class="stat"><div class="k">预报 / 实收 / 回执（行）</div><div class="v">{{ d.expect_count }} / {{ d.receive_count }} / {{ d.confirm_count }}</div></div>
      <div class="stat"><div class="k">未决差额</div><div class="v">{{ d.pending_variance }}</div></div>
      <div class="stat">
        <div class="k">结案</div>
        <div class="v"><span class="tag" :class="d.sealed ? 'seal' : 'bad'">{{ d.sealed ? '已结案' : '未结案' }}</span></div>
      </div>
    </div>
    <div class="grid" v-if="d && d.latest_batch">
      <div class="stat"><div class="k">折算件数 预报</div><div class="v">{{ fmt(d.pieces.expect) }}</div></div>
      <div class="stat"><div class="k">折算件数 实收</div><div class="v">{{ fmt(d.pieces.receive) }}</div></div>
      <div class="stat"><div class="k">折算件数 回执</div><div class="v">{{ fmt(d.pieces.confirm) }}</div></div>
      <div class="stat"><div class="k">对齐 / 差额</div><div class="v">{{ d.buckets.matched }} / {{ d.buckets.variance }}</div></div>
    </div>
    <div class="panel" v-if="d && d.latest_batch">
      <h2>最近对账批次</h2>
      <p>{{ d.latest_batch.batch_no }} · 对齐 {{ d.latest_batch.matched_count }} · 差额 {{ d.latest_batch.variance_count }} · {{ d.latest_batch.status }}</p>
      <p class="buckets">
        <span class="tag warn">缺箱规 {{ d.buckets.unit_miss }}</span>
        <span class="tag warn">单位不符 {{ d.buckets.unit_mismatch }}</span>
        <small class="hint">两类桶非空时不可结案。</small>
      </p>
    </div>
    <p class="msg">{{ err }}</p>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const d = ref(null)
const err = ref('')
function fmt(x) { return Number(x).toLocaleString() }
async function load() {
  err.value = ''
  try { d.value = await api('/dashboard') } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
