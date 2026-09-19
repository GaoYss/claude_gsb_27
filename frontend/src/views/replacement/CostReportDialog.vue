<template>
  <el-dialog :model-value="visible" title="更换费用归属报表" width="920px" top="6vh"
             destroy-on-close @update:model-value="close">
    <div v-loading="loading">
      <div class="toolbar">
        <el-radio-group v-model="groupBy" size="small" @change="load">
          <el-radio-button value="month">按月</el-radio-button>
          <el-radio-button value="quarter">按季</el-radio-button>
          <el-radio-button value="year">按年</el-radio-button>
        </el-radio-group>
        <el-date-picker v-model="dateRange" type="daterange" unlink-panels size="small"
                        value-format="YYYY-MM-DD" start-placeholder="更换日期起"
                        end-placeholder="更换日期止" @change="onDateChange" />
        <div style="width: 220px">
          <GreenSpaceSelect v-model="greenSpaceId" placeholder="全部绿地" @update:model-value="load" />
        </div>
      </div>

      <div class="stat-grid">
        <StatCard label="费用合计" :value="formatCurrency(report?.total_amount ?? 0)" tone="info" icon="Money" />
        <StatCard label="更换明细" :value="formatNumber(report?.total_count ?? 0)" unit="条" icon="Cherry" />
        <StatCard label="更换数量" :value="formatNumber(report?.total_quantity ?? 0)" icon="Histogram" />
        <StatCard label="涉及绿地" :value="formatNumber(report?.green_space_count ?? 0)" unit="处" icon="MapLocation" />
      </div>

      <el-table :data="report?.items || []" size="small" border max-height="420" empty-text="当前条件下暂无费用数据">
        <el-table-column prop="period_label" label="时间段" width="140" />
        <el-table-column label="所属绿地" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" @click="drillSpace(row)">{{ row.name || `绿地#${row.green_space_id}` }}</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="district" label="行政区" width="100" />
        <el-table-column prop="count" label="明细条数" width="90" align="right" />
        <el-table-column label="更换数量" width="110" align="right">
          <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
        </el-table-column>
        <el-table-column label="更换费用" width="130" align="right">
          <template #default="{ row }">
            <strong>{{ formatCurrency(row.amount) }}</strong>
          </template>
        </el-table-column>
      </el-table>
      <div class="hint">口径与更换列表一致：金额 = 数量 × 单价（未填单价的明细不计入金额）；点击绿地名称可下钻到该绿地的更换明细。</div>
    </div>

    <template #footer>
      <el-button @click="close">关闭</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'

import { plantReplacementApi } from '@/api'
import GreenSpaceSelect from '@/components/common/GreenSpaceSelect.vue'
import StatCard from '@/components/common/StatCard.vue'
import { formatCurrency, formatNumber } from '@/utils/format'

const router = useRouter()

const visible = ref(false)
const loading = ref(false)
const report = ref(null)
const groupBy = ref('month')
const greenSpaceId = ref(null)
const dateRange = ref([])

async function open() {
  visible.value = true
  await load()
}

function close() {
  visible.value = false
}

function onDateChange(value) {
  dateRange.value = value || []
  load()
}

async function load() {
  loading.value = true
  try {
    const params = { group_by: groupBy.value }
    if (greenSpaceId.value) params.green_space_id = greenSpaceId.value
    if (dateRange.value?.[0]) params.date_from = dateRange.value[0]
    if (dateRange.value?.[1]) params.date_to = dateRange.value[1]
    report.value = await plantReplacementApi.costReport(params)
  } finally {
    loading.value = false
  }
}

function drillSpace(row) {
  router.push({
    name: 'replacement-list',
    query: { green_space_id: row.green_space_id },
  })
  close()
}

defineExpose({ open })
</script>

<style scoped>
.toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
}

.stat-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.hint {
  margin-top: 10px;
  color: #909399;
  font-size: 12px;
  line-height: 1.6;
}
</style>
