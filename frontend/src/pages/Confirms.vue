<template>
  <div>
    <div class="hero"><div><h1>回执</h1><p>供应商回执，三方对齐第三腿。常按箱申报——数量 + 单位照实填，对账时按箱规折成件再比。</p></div><button @click="load">刷新</button></div>
    <div class="panel">
      <div class="row">
        <input v-model="form.confirm_no" placeholder="回执号" />
        <input v-model="form.supplier_code" placeholder="供应商编码" />
        <input v-model="form.sku" placeholder="货号" />
        <input v-model="form.dock_day" placeholder="到货日" />
        <input v-model.number="form.qty" type="number" placeholder="数量" />
        <input v-model="form.unit" class="unit" placeholder="单位" />
        <button @click="add">登记回执</button>
      </div>
      <p class="hint">单位请填实际申报单位（如 箱 / 件）。缺箱规或不可换算的回执不会被静默按 1:1 比对，而是在对账中进入 unit_miss / unit_mismatch 隔离桶。</p>
      <p class="msg">{{ err }}</p>
      <p class="okmsg">{{ ok }}</p>
      <table>
        <thead><tr><th>回执号</th><th>供应商</th><th>货号</th><th>到货日</th><th>数量</th><th>单位</th></tr></thead>
        <tbody>
          <tr v-for="r in rows" :key="r.id"><td>{{ r.confirm_no }}</td><td>{{ r.supplier_code }}</td><td>{{ r.sku }}</td><td>{{ r.dock_day }}</td><td>{{ r.qty }}</td><td><span class="unitbadge">{{ r.unit }}</span></td></tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const rows = ref([])
const err = ref('')
const ok = ref('')
const form = ref({ confirm_no: '', supplier_code: 'SUP-A', sku: '', dock_day: '2026-11-18', qty: 1, unit: '箱' })
async function load() { rows.value = await api('/confirms') }
async function add() {
  err.value = ''; ok.value = ''
  try {
    await api('/confirms', { method: 'POST', body: JSON.stringify(form.value) })
    ok.value = '已登记'
    await load()
  } catch (e) { err.value = e.message }
}
onMounted(load)
</script>
