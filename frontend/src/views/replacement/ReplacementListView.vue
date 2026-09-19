<template>
  <div class="page">
    <PageHeader title="绿植更换记录" description="登记绿地内植株的更换、补植与品种改造，自动核算更换金额">
      <template #actions>
        <el-button :icon="'Upload'" @click="importDialog.open()">批量导入</el-button>
        <el-button type="primary" :icon="'Plus'" @click="formDialog.open()">登记更换记录</el-button>
      </template>
    </PageHeader>

    <el-alert v-if="filters.task_id" type="info" class="task-filter-alert" :closable="false">
      <div class="task-filter-content">
        <span>正在查看任务 {{ taskHint || `#${filters.task_id}` }} 关联的更换明细</span>
        <el-button link type="primary" @click="clearTaskFilter">清除筛选</el-button>
      </div>
    </el-alert>

    <div class="panel">
      <div class="filter-bar">
        <el-input v-model="filters.keyword" placeholder="编号 / 植株 / 供苗单位" clearable
                  :prefix-icon="'Search'" @keyup.enter="search" @clear="search" />
        <div style="width: 220px">
          <GreenSpaceSelect v-model="filters.green_space_id" placeholder="按绿地筛选" @update:model-value="search" />
        </div>
        <el-select v-model="filters.plant_category" placeholder="植物类别" clearable @change="search">
          <el-option v-for="item in categoryOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="filters.reason" placeholder="更换原因" clearable @change="search">
          <el-option v-for="item in reasonOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-date-picker v-model="dateRange" type="daterange" unlink-panels value-format="YYYY-MM-DD"
                        start-placeholder="更换日期起" end-placeholder="更换日期止" @change="onDateChange" />
        <el-button type="primary" :icon="'Search'" @click="search">查询</el-button>
        <el-button :icon="'RefreshLeft'" @click="reset">重置</el-button>
      </div>
    </div>

    <div class="stat-grid">
      <StatCard label="更换记录" :value="formatNumber(summary?.total_count ?? 0)" unit="条"
                :hint="`合计数量 ${formatNumber(summary?.total_quantity ?? 0)}`" icon="Cherry" />
      <StatCard label="更换金额" :value="formatCurrency(summary?.total_amount ?? 0)"
                hint="按登记的单价与数量核算" tone="info" icon="Money" />
      <StatCard label="涉及植物类别" :value="formatNumber(summary?.by_category?.length ?? 0)" unit="类"
                :hint="(summary?.by_category || []).map((item) => item.label).join('、') || '暂无数据'" icon="Grape" />
      <StatCard label="主要更换原因"
                :value="topReason ? topReason.label : '-'"
                :hint="topReason ? `${formatNumber(topReason.count)} 次，${formatNumber(topReason.quantity)} 单位` : '暂无数据'"
                icon="Warning" />
    </div>

    <div class="panel">
      <div class="table-toolbar">
        <span class="summary-text">
          共 <strong>{{ meta.total }}</strong> 条更换记录，
          数量合计 <strong>{{ formatNumber(summary?.total_quantity ?? 0) }}</strong>，
          金额合计 <strong>{{ formatCurrency(summary?.total_amount ?? 0) }}</strong>
        </span>
        <el-button :icon="'Refresh'" text @click="load">刷新</el-button>
      </div>

      <el-table :data="items" v-loading="loading" border stripe>
        <el-table-column type="expand">
          <template #default="{ row }">
            <div class="expand-detail">
              <span><b>原植株状况：</b>{{ row.old_plant_status_label || '-' }}</span>
              <span><b>单价：</b>{{ formatCurrency(row.unit_price) }}</span>
              <span><b>供苗单位：</b>{{ row.supplier || '-' }}</span>
              <span><b>登记人：</b>{{ row.operator || '-' }}</span>
              <span><b>关联养护记录：</b>{{ row.record ? `${row.record.record_no}（${formatDate(row.record.record_date)}）` : '未关联' }}</span>
              <span><b>关联任务：</b>{{ row.record?.task ? `${row.record.task.task_no} ${row.record.task.title}` : '未关联' }}</span>
              <span><b>导入批次：</b>{{ row.import_batch ? `${row.import_batch}（行 ${row.import_line}）` : '手工登记' }}</span>
              <span><b>登记时间：</b>{{ formatDateTime(row.created_at) }}</span>
              <span v-if="row.remark"><b>备注：</b>{{ row.remark }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="replacement_no" label="编号" width="150" />
        <el-table-column label="所属绿地" min-width="150" show-overflow-tooltip>
          <template #default="{ row }">{{ row.green_space?.name || '-' }}</template>
        </el-table-column>
        <el-table-column label="植株名称" width="150">
          <template #default="{ row }">
            <div>{{ row.plant_name }}</div>
            <EnumTag group="plant_category" :value="row.plant_category" :label="row.plant_category_label" />
          </template>
        </el-table-column>
        <el-table-column prop="spec" label="规格" width="120">
          <template #default="{ row }">{{ row.spec || '-' }}</template>
        </el-table-column>
        <el-table-column label="数量" width="110" align="right">
          <template #default="{ row }">
            {{ formatNumber(row.quantity) }} {{ row.unit_label }}
          </template>
        </el-table-column>
        <el-table-column label="更换原因" width="115">
          <template #default="{ row }">
            <EnumTag group="replacement_reason" :value="row.reason" :label="row.reason_label" />
          </template>
        </el-table-column>
        <el-table-column prop="replace_date" label="更换日期" width="105" />
        <el-table-column label="金额" width="115" align="right">
          <template #default="{ row }">
            <span :class="{ 'amount-missing': row.amount === null }">{{ formatCurrency(row.amount) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="130" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="formDialog.open(row)">编辑</el-button>
            <el-button link type="danger" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        background
        layout="total, sizes, prev, pager, next, jumper"
        :total="meta.total"
        :current-page="meta.page"
        :page-size="meta.page_size"
        :page-sizes="[10, 20, 50]"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <div class="panel">
      <div class="table-toolbar">
        <span class="panel-title">更换原因汇总</span>
        <span class="summary-text">按当前筛选条件统计</span>
      </div>
      <el-table :data="summary?.by_reason || []" size="small" border empty-text="暂无数据">
        <el-table-column prop="label" label="更换原因" width="140" />
        <el-table-column prop="count" label="记录条数" width="110" />
        <el-table-column label="更换数量" width="130">
          <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
        </el-table-column>
        <el-table-column label="更换金额" width="140">
          <template #default="{ row }">{{ formatCurrency(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="占比" min-width="200">
          <template #default="{ row }">
            <el-progress :percentage="shareOf(row.quantity)" :stroke-width="12"
                         :color="'#48a17a'" :format="() => `${shareOf(row.quantity)}%`" />
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="panel">
      <div class="table-toolbar">
        <span class="panel-title">更换费用归集</span>
        <span class="summary-text">按当前筛选条件，归集到绿地与月份</span>
      </div>
      <div class="cost-grid">
        <el-table :data="costSummary?.by_green_space || []" size="small" border empty-text="暂无数据">
          <el-table-column label="绿地" min-width="180" show-overflow-tooltip>
            <template #default="{ row }">{{ row.code }} {{ row.name }}</template>
          </el-table-column>
          <el-table-column prop="count" label="记录条数" width="90" />
          <el-table-column label="更换数量" width="110">
            <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
          </el-table-column>
          <el-table-column label="费用金额" width="130" align="right">
            <template #default="{ row }">{{ formatCurrency(row.amount) }}</template>
          </el-table-column>
        </el-table>
        <el-table :data="costSummary?.by_month || []" size="small" border empty-text="暂无数据">
          <el-table-column prop="month" label="月份" width="110" />
          <el-table-column prop="count" label="记录条数" width="90" />
          <el-table-column label="更换数量" width="110">
            <template #default="{ row }">{{ formatNumber(row.quantity) }}</template>
          </el-table-column>
          <el-table-column label="费用金额" align="right">
            <template #default="{ row }">{{ formatCurrency(row.amount) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <ReplacementFormDialog ref="formDialog" @saved="reloadAll" />
    <ReplacementImportDialog ref="importDialog" @saved="reloadAll" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'

import { plantReplacementApi } from '@/api'
import EnumTag from '@/components/common/EnumTag.vue'
import GreenSpaceSelect from '@/components/common/GreenSpaceSelect.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatCard from '@/components/common/StatCard.vue'
import { useEnumOptions } from '@/composables/useEnumOptions'
import { useListQuery } from '@/composables/useListQuery'
import { formatCurrency, formatDate, formatDateTime, formatNumber } from '@/utils/format'

import ReplacementFormDialog from './ReplacementFormDialog.vue'
import ReplacementImportDialog from './ReplacementImportDialog.vue'

const route = useRoute()
const formDialog = ref(null)
const importDialog = ref(null)
const dateRange = ref([])
const taskHint = ref(route.query.task_no || '')

const { options: categoryOptions } = useEnumOptions('plant_category')
const { options: reasonOptions } = useEnumOptions('replacement_reason')

const { filters, meta, items, summary, loading, load, search: searchList, resetFilters, handlePageChange, handleSizeChange } =
  useListQuery(plantReplacementApi.list, {
    initialFilters: {
      keyword: '',
      green_space_id: route.query.green_space_id ? Number(route.query.green_space_id) : null,
      plant_category: '',
      reason: '',
      task_id: route.query.task_id ? Number(route.query.task_id) : null,
      date_from: '',
      date_to: '',
    },
  })

const costSummary = ref(null)

function activeParams() {
  const params = {}
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== null && value !== undefined && value !== '') params[key] = value
  })
  return params
}

async function loadCostSummary() {
  try {
    costSummary.value = await plantReplacementApi.costSummary(activeParams())
  } catch {
    costSummary.value = null
  }
}

function search() {
  loadCostSummary()
  return searchList()
}

function reloadAll() {
  loadCostSummary()
  return load()
}

function clearTaskFilter() {
  filters.task_id = null
  taskHint.value = ''
  search()
}

onMounted(loadCostSummary)

const topReason = computed(() => {
  const rows = [...(summary.value?.by_reason || [])]
  if (!rows.length) return null
  return rows.sort((a, b) => b.quantity - a.quantity)[0]
})

function shareOf(quantity) {
  const total = summary.value?.total_quantity || 0
  if (!total) return 0
  return Math.round((Number(quantity) / total) * 1000) / 10
}

function onDateChange(value) {
  filters.date_from = value?.[0] || ''
  filters.date_to = value?.[1] || ''
  search()
}

function reset() {
  dateRange.value = []
  taskHint.value = ''
  resetFilters()
  loadCostSummary()
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除更换记录「${row.replacement_no}」吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
    await plantReplacementApi.remove(row.id)
    ElMessage.success('绿植更换记录已删除')
    await reloadAll()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
  }
}
</script>

<style scoped>
.pager {
  margin-top: 16px;
  justify-content: flex-end;
}

.panel-title {
  font-weight: 600;
}

.amount-missing {
  color: #e6a23c;
}

.task-filter-alert {
  margin-bottom: 16px;
}

.task-filter-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.cost-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(380px, 1fr));
  gap: 16px;
}

.expand-detail {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 6px 16px;
  padding: 4px 12px;
  color: #606266;
  font-size: 13px;
}
</style>
