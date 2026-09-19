<template>
  <el-dialog :model-value="visible" title="批量导入绿植更换记录" width="860px" top="6vh"
             destroy-on-close @update:model-value="close">
    <el-alert type="info" :closable="false" show-icon class="tip">
      <template #title>
        同一批次号重复提交不会重复入账；批次内与已入账记录内容完全一致的明细会自动判重跳过，逐行返回结果。
      </template>
    </el-alert>

    <el-form label-width="110px">
      <el-form-item label="批次号" required>
        <el-input v-model="batchNo" placeholder="幂等键，如 IMP-20260410-01；重复提交请保持一致" maxlength="64" />
      </el-form-item>
      <el-form-item label="数据来源">
        <el-input v-model="source" placeholder="如 excel / 供应商系统，选填" maxlength="32" style="width: 280px" />
      </el-form-item>
      <el-form-item label="明细 JSON">
        <el-input v-model="jsonText" type="textarea" :rows="10"
                  placeholder='[{"green_space_id":1,"plant_name":"香樟","plant_category":"tree","quantity":10,"unit":"plant","reason":"dead","replace_date":"2026-04-10","supplier":"萧山苗圃","unit_price":100}]' />
      </el-form-item>
      <el-form-item>
        <el-upload :auto-upload="false" :show-file-list="false" accept=".json" :on-change="onFile">
          <el-button :icon="'Upload'">选择 JSON 文件填充</el-button>
        </el-upload>
        <el-button text type="primary" @click="loadExample">填入示例</el-button>
      </el-form-item>
    </el-form>

    <div v-if="result" class="result">
      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="入账">
          <el-tag type="success">{{ result.imported_count }} 条</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="判重跳过">
          <el-tag type="warning">{{ result.duplicate_count }} 条</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="校验失败">
          <el-tag :type="result.failed_count ? 'danger' : 'info'">{{ result.failed_count }} 条</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="批次号">{{ result.batch_no }}</el-descriptions-item>
      </el-descriptions>

      <el-tabs v-if="hasDetail" class="result-tabs">
        <el-tab-pane :label="`入账（${importedRows.length}）`">
          <el-table :data="importedRows" size="small" border max-height="200">
            <el-table-column prop="row" label="行号" width="80" />
            <el-table-column prop="replacement_no" label="生成编号" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane :label="`判重（${duplicateRows.length}）`">
          <el-table :data="duplicateRows" size="small" border max-height="200">
            <el-table-column prop="row" label="行号" width="80" />
            <el-table-column prop="reason" label="判重原因" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane :label="`失败（${failedRows.length}）`">
          <el-table :data="failedRows" size="small" border max-height="200">
            <el-table-column prop="row" label="行号" width="80" />
            <el-table-column label="错误">
              <template #default="{ row }">
                <span v-for="(msg, key) in row.errors" :key="key" class="error-line">【{{ fieldLabel(key) }}】{{ msg }}</span>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <template #footer>
      <el-button @click="close">关闭</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">开始导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { plantReplacementApi } from '@/api'

const emit = defineEmits(['imported'])

const visible = ref(false)
const submitting = ref(false)
const batchNo = ref('')
const source = ref('')
const jsonText = ref('')
const result = ref(null)

const importedRows = computed(() => result.value?.result_detail?.imported || [])
const duplicateRows = computed(() => result.value?.result_detail?.duplicates || [])
const failedRows = computed(() => result.value?.result_detail?.failures || [])
const hasDetail = computed(
  () => importedRows.value.length || duplicateRows.value.length || failedRows.value.length,
)

const FIELD_LABELS = {
  _: '整行',
  green_space_id: '所属绿地',
  maintenance_record_id: '关联养护记录',
  plant_name: '植株名称',
  plant_category: '植物类别',
  spec: '规格',
  quantity: '更换数量',
  unit: '计量单位',
  reason: '更换原因',
  old_plant_status: '原植株状况',
  replace_date: '更换日期',
  supplier: '供苗单位',
  unit_price: '单价',
  operator: '登记人',
  remark: '备注',
}
function fieldLabel(key) {
  return FIELD_LABELS[key] || key
}

function open() {
  result.value = null
  visible.value = true
}

function close() {
  visible.value = false
}

function loadExample() {
  jsonText.value = JSON.stringify(
    [
      {
        green_space_id: 1, plant_name: '香樟', plant_category: 'tree', spec: '胸径 12cm',
        quantity: 10, unit: 'plant', reason: 'dead', replace_date: '2026-04-10',
        supplier: '萧山苗木合作社', unit_price: 100, operator: '王海涛',
      },
    ],
    null,
    2,
  )
}

function onFile(file) {
  const reader = new FileReader()
  reader.onload = () => {
    jsonText.value = String(reader.result || '')
  }
  reader.onerror = () => ElMessage.error('文件读取失败')
  reader.readAsText(file.raw)
}

async function submit() {
  if (!batchNo.value.trim()) {
    ElMessage.warning('请填写批次号（幂等键）')
    return
  }
  let items
  try {
    items = JSON.parse(jsonText.value || '[]')
  } catch {
    ElMessage.error('明细 JSON 格式不正确，请检查')
    return
  }
  if (!Array.isArray(items)) {
    ElMessage.error('明细 JSON 必须是数组')
    return
  }
  submitting.value = true
  try {
    const payload = { batch_no: batchNo.value.trim(), items }
    if (source.value.trim()) payload.source = source.value.trim()
    result.value = await plantReplacementApi.importBatch(payload)
    ElMessage.success(
      `导入完成：入账 ${result.value.imported_count} 条，判重 ${result.value.duplicate_count} 条，失败 ${result.value.failed_count} 条`,
    )
    if (result.value.imported_count > 0) emit('imported')
  } catch (error) {
    if (error?.details?.batch_no) ElMessage.error(error.details.batch_no)
    if (error?.details?.items) ElMessage.error(error.details.items)
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.tip {
  margin-bottom: 16px;
}

.result {
  margin-top: 8px;
}

.error-line {
  display: block;
  color: #f56c6c;
  font-size: 12px;
  line-height: 1.7;
}
</style>
