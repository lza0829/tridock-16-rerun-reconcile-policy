<template>
  <div>
    <div class="hero">
      <div>
        <h1>设置</h1>
        <p>拨到货日（夹具日，非墙钟强绑）；维护箱规表，回执按箱申报时以此折成件。</p>
      </div>
    </div>
    <div class="panel">
      <h2>到货日</h2>
      <div class="row">
        <input v-model="day" placeholder="YYYY-MM-DD" />
        <button @click="save">保存到货日</button>
      </div>
      <p class="msg">{{ err }}</p>
      <p class="okmsg">{{ ok }}</p>
    </div>
    <div class="panel">
      <h2>箱规表</h2>
      <p class="hint">按 供应商+货号+单位 维护箱规（单位 → 件）。缺箱规的非件单位回执在对账中进入 unit_miss，不会被当成 1:1 比对。已结案批次已快照折算结果，事后改箱规不会撬动它。</p>
      <div class="row">
        <input v-model="spec.supplier_code" placeholder="供应商编码" />
        <input v-model="spec.sku" placeholder="货号" />
        <input v-model="spec.unit" class="unit" placeholder="单位（如 箱）" />
        <input v-model="spec.base_unit" class="unit" placeholder="基准单位" />
        <input v-model.number="spec.pack_size" type="number" placeholder="每单位件数" />
        <button @click="saveSpec">保存箱规</button>
      </div>
      <p class="msg">{{ specErr }}</p>
      <p class="okmsg">{{ specOk }}</p>
      <table>
        <thead><tr><th>供应商</th><th>货号</th><th>单位</th><th>基准</th><th>箱规</th><th>更新时间</th><th></th></tr></thead>
        <tbody>
          <tr v-for="s in specs" :key="s.id">
            <td>{{ s.supplier_code }}</td><td>{{ s.sku }}</td><td><span class="unitbadge">{{ s.unit }}</span></td>
            <td>{{ s.base_unit }}</td><td>{{ s.pack_size }}</td><td><small>{{ s.updated_at }}</small></td>
            <td><button class="secondary" @click="delSpec(s.id)">删除</button></td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const day = ref('')
const err = ref('')
const ok = ref('')
const specs = ref([])
const spec = ref({ supplier_code: 'SUP-B', sku: '', unit: '箱', base_unit: '件', pack_size: 20 })
const specErr = ref('')
const specOk = ref('')
async function load() {
  const s = await api('/settings')
  day.value = s.dock_day || ''
  specs.value = await api('/pack-specs')
}
async function save() {
  err.value = ''; ok.value = ''
  try {
    await api('/settings/dock-day', { method: 'POST', body: JSON.stringify({ dock_day: day.value }) })
    ok.value = '已保存'
  } catch (e) { err.value = e.message }
}
async function saveSpec() {
  specErr.value = ''; specOk.value = ''
  try {
    await api('/pack-specs', { method: 'POST', body: JSON.stringify(spec.value) })
    specOk.value = '箱规已保存（下次对账生效；已结案批次不受影响）'
    specs.value = await api('/pack-specs')
  } catch (e) { specErr.value = e.message }
}
async function delSpec(id) {
  specErr.value = ''; specOk.value = ''
  try {
    await api(`/pack-specs/${id}`, { method: 'DELETE' })
    specOk.value = '已删除'
    specs.value = await api('/pack-specs')
  } catch (e) { specErr.value = e.message }
}
onMounted(load)
</script>
