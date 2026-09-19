<template>
  <el-dialog :model-value="visible" title="批量导入绿植更换记录" width="720px" top="6vh"
             destroy-on-close @update:model-value="close">
    <template v-if="!result">
      <el-alert type="info" :closable="false" class="import-tip">
        同一批次号重复导入时，已存在的行会自动跳过，不会重复入账；任一行校验不通过则整批不写入。
      </el-alert>
      <el-form label-width="100px">
        <el-form-item label="导入批次号" required :error="topErrors.batch_no">
          <el-input v-model="batchNo" maxlength="64" placeholder="如 IMP-20260918-001，同一批数据必须一致" />
        </el-form-item>
        <el-form-item label="明细 JSON" required :error="topErrors.items">
          <el-input v-model="itemsText" type="textarea" :rows="10"
                    placeholder='[{"line_no": "1", "green_space_id": 1, "plant_name": "香樟", ...}]' />
          <div class="dialog-actions">
            <el-button size="small" @click="fillSample">填入示例</el-button>
            <el-button size="small" @click="pickFile">从 JSON 文件读取</el-button>
            <input ref="fileInput" type="file" accept=".json,application/json" hidden @change="readFile" />
          </div>
        </el-form-item>
      </el-form>
      <el-alert v-if="lineErrors.length" type="error" :closable="false" title="以下行未通过校验，整批未写入">
        <ul class="error-list">
          <li v-for="item in lineErrors" :key="item.line_no">
            行 {{ item.line_no }}：{{ formatErrors(item.errors) }}
          </li>
        </ul>
      </el-alert>
    </template>

    <template v-else>
      <el-result icon="success" :title="`导入完成：新增 ${result.created_count} 条，跳过已存在 ${result.skipped_count} 条`"
                 :sub-title="`批次号 ${result.batch_no}，重复导入同一批次不会重复入账`" />
      <el-table :data="result.items" size="small" border max-height="320">
        <el-table-column prop="line_no" label="行号" width="90" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="row.status === 'created' ? 'success' : 'info'" effect="plain">
              {{ row.status === 'created' ? '已入账' : '已存在跳过' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="replacement_no" label="更换记录编号" />
      </el-table>
    </template>

    <template #footer>
      <template v-if="!result">
        <el-button @click="close">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="submit">开始导入</el-button>
      </template>
      <el-button v-else type="primary" @click="close">完成</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { plantReplacementApi } from '@/api'

const emit = defineEmits(['saved'])

const visible = ref(false)
const submitting = ref(false)
const batchNo = ref('')
const itemsText = ref('')
const result = ref(null)
const lineErrors = ref([])
const topErrors = ref({})
const fileInput = ref(null)

const SAMPLE = [
  {
    line_no: '1',
    green_space_id: 1,
    plant_name: '香樟',
    plant_category: 'tree',
    spec: '胸径 25-30cm',
    quantity: 10,
    unit: 'plant',
    reason: 'dead',
    old_plant_status: 'dead',
    replace_date: '2026-03-15',
    supplier: '萧山苗木合作社',
    unit_price: 128.5,
    operator: '王海涛',
  },
]

function open() {
  batchNo.value = ''
  itemsText.value = ''
  result.value = null
  lineErrors.value = []
  topErrors.value = {}
  visible.value = true
}

function close() {
  visible.value = false
}

function fillSample() {
  itemsText.value = JSON.stringify(SAMPLE, null, 2)
}

function pickFile() {
  fileInput.value?.click()
}

function readFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const reader = new FileReader()
  reader.onload = () => {
    try {
      const parsed = JSON.parse(reader.result)
      if (Array.isArray(parsed)) {
        itemsText.value = JSON.stringify(parsed, null, 2)
      } else if (parsed && Array.isArray(parsed.items)) {
        if (parsed.batch_no) batchNo.value = String(parsed.batch_no)
        itemsText.value = JSON.stringify(parsed.items, null, 2)
      } else {
        ElMessage.error('文件内容应为明细数组，或 {"batch_no": "...", "items": [...]}')
      }
    } catch {
      ElMessage.error('文件不是合法的 JSON')
    }
  }
  reader.readAsText(file)
}

function formatErrors(errors) {
  return Object.entries(errors || {})
    .map(([field, message]) => `${field}：${message}`)
    .join('；')
}

async function submit() {
  lineErrors.value = []
  topErrors.value = {}
  if (!batchNo.value.trim()) {
    topErrors.value = { batch_no: '请输入导入批次号' }
    return
  }
  let items
  try {
    items = JSON.parse(itemsText.value || '[]')
  } catch {
    topErrors.value = { items: '明细 JSON 格式不正确' }
    return
  }
  if (!Array.isArray(items) || !items.length) {
    topErrors.value = { items: '明细必须是非空数组' }
    return
  }
  submitting.value = true
  try {
    result.value = await plantReplacementApi.importBatch({
      batch_no: batchNo.value.trim(),
      items,
    })
    emit('saved')
  } catch (error) {
    const details = error?.details || {}
    if (Array.isArray(details.items)) {
      lineErrors.value = details.items
    } else {
      topErrors.value = details
    }
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.import-tip {
  margin-bottom: 16px;
}

.dialog-actions {
  display: flex;
  gap: 8px;
  margin-top: 8px;
}

.error-list {
  margin: 4px 0 0;
  padding-left: 18px;
}
</style>
