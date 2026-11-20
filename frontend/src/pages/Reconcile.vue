<template>
  <div>
    <div class="hero">
      <div>
        <h1>三联对账</h1>
        <p>按供应商+货号+到货日对齐三数量，一律折成「件」再比：回执 qty × 箱规 = 件。缺箱规进 unit_miss、单位不可换算进 unit_mismatch，绝不按 1:1 硬比；两类桶清空前不得结案。</p>
      </div>
    </div>
    <div class="panel">
      <div class="row">
        <input v-model="day" placeholder="到货日" />
        <button @click="run">跑三联对账</button>
        <button class="warn" @click="seal">结案封印</button>
        <button class="secondary" @click="load">刷新</button>
      </div>
      <p class="msg">{{ err }}</p>
      <p class="okmsg">{{ ok }}</p>
      <div v-if="batch" class="stats">
        <div class="stat"><div class="k">批次</div><div class="v small">{{ batch.batch_no }}</div></div>
        <div class="stat"><div class="k">对齐</div><div class="v">{{ batch.matched_count }}</div></div>
        <div class="stat"><div class="k">差额</div><div class="v">{{ batch.variance_count }}</div></div>
        <div class="stat"><div class="k">缺箱规</div><div class="v badv">{{ batch.unit_miss_count }}</div></div>
        <div class="stat"><div class="k">单位不符</div><div class="v badv">{{ batch.unit_mismatch_count }}</div></div>
        <div class="stat"><div class="k">状态</div><div class="v small">{{ batch.status }}</div></div>
      </div>
      <p v-if="batch" class="pieces">
        折算件数 · 预报 {{ fmt(batch.expect_pieces) }} / 实收 {{ fmt(batch.receive_pieces) }} / 回执 {{ fmt(batch.confirm_pieces) }}
      </p>
    </div>
    <div class="panel">
      <h2>对齐行</h2>
      <p class="hint">「件」列为折算后数量；「原始」列为申报原值×单位。差额与隔离行以标签区分。</p>
      <table>
        <thead><tr><th>供应商</th><th>货号</th><th>预报</th><th>实收</th><th>回执</th><th>箱规折算</th><th>状态</th></tr></thead>
        <tbody>
          <tr v-for="r in matches" :key="r.id">
            <td>{{ r.supplier_code }}</td><td>{{ r.sku }}</td>
            <td><div class="cell">{{ r.expect_qty === null ? '—' : fmt(r.expect_qty) }}</div><small>{{ raw(r.expect_raw_qty, r.expect_unit) }}</small></td>
            <td><div class="cell">{{ r.receive_qty === null ? '—' : fmt(r.receive_qty) }}</div><small>{{ raw(r.receive_raw_qty, r.receive_unit) }}</small></td>
            <td><div class="cell">{{ r.confirm_qty === null ? '—' : fmt(r.confirm_qty) }}</div><small>{{ raw(r.confirm_raw_qty, r.confirm_unit) }}</small></td>
            <td><small>{{ r.convert_rule || '—' }}</small></td>
            <td>
              <span class="tag" :class="tagClass(r.bucket)">{{ bucketLabel(r.bucket) }}</span>
              <small v-if="r.bucket_reason" class="why">{{ r.bucket_reason }}</small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="panel">
      <h2>差额处置</h2>
      <table>
        <thead><tr><th>供应商</th><th>货号</th><th>三数量（件）</th><th>命运</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="r in variances" :key="r.id">
            <td>{{ r.supplier_code }}</td><td>{{ r.sku }}</td>
            <td>{{ fmt(r.expect_qty) }} / {{ fmt(r.receive_qty) }} / {{ fmt(r.confirm_qty) }}</td>
            <td>{{ r.fate }}</td>
            <td>
              <button class="secondary" @click="fate(r.id, 'accept_short')">认短</button>
              <button class="secondary" @click="fate(r.id, 'accept_over')">认溢</button>
              <button class="secondary" @click="fate(r.id, 'quarantine')">隔离</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const day = ref('2026-11-18')
const batch = ref(null)
const matches = ref([])
const variances = ref([])
const err = ref('')
const ok = ref('')
const BUCKETS = { matched: '对齐', variance: '差额', unit_miss: '缺箱规', unit_mismatch: '单位不符' }
const TAGS = { matched: 'ok', variance: 'bad', unit_miss: 'warn', unit_mismatch: 'warn' }
function bucketLabel(b) { return BUCKETS[b] || b }
function tagClass(b) { return TAGS[b] || 'bad' }
function fmt(x) { return x === null || x === undefined ? '—' : Number(x).toLocaleString() }
function raw(q, u) { return `${q} ${u}` }
async function load() {
  err.value = ''
  const batches = await api(`/reconcile/batches?dock_day=${encodeURIComponent(day.value)}`)
  batch.value = batches[0] || null
  if (!batch.value) { matches.value = []; variances.value = []; return }
  matches.value = await api(`/reconcile/matches?batch_id=${batch.value.id}`)
  variances.value = await api(`/reconcile/variances?batch_id=${batch.value.id}`)
}
async function run() {
  err.value = ''; ok.value = ''
  try {
    batch.value = await api('/reconcile/run', { method: 'POST', body: JSON.stringify({ dock_day: day.value }) })
    ok.value = '对账完成'
    await load()
  } catch (e) { err.value = e.message }
}
async function seal() {
  err.value = ''; ok.value = ''
  try {
    batch.value = await api('/reconcile/seal', { method: 'POST', body: JSON.stringify({ dock_day: day.value }) })
    ok.value = '已结案'
    await load()
  } catch (e) { err.value = e.message }
}
async function fate(id, f) {
  err.value = ''; ok.value = ''
  try {
    await api(`/reconcile/variances/${id}/fate`, { method: 'POST', body: JSON.stringify({ fate: f }) })
    ok.value = '已更新命运'
    await load()
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
