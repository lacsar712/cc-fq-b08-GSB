<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">批量入队</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新样例" @click="load" :loading="loading" />
    </div>

    <q-banner v-if="auth.role !== 'bioops'" class="bg-warning text-dark q-mb-md" rounded>
      审计员不可进入批量入队页，请使用 bioops 账号。
    </q-banner>

    <q-card v-else flat bordered class="q-mb-lg">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">勾选样例（可多选，损坏样例会入队但作业将在 ParseActor 失败）</div>
        <q-table
          flat
          bordered
          row-key="id"
          :rows="rows"
          :columns="columns"
          :loading="loading"
          selection="multiple"
          v-model:selected="selected"
          hide-pagination
          :pagination="{ rowsPerPage: 0 }"
        >
          <template #body-cell-is_broken="props">
            <q-td :props="props">
              <q-badge :color="props.row.is_broken ? 'negative' : 'positive'">
                {{ props.row.is_broken ? '损坏' : '合格' }}
              </q-badge>
            </q-td>
          </template>
        </q-table>
      </q-card-section>
      <q-card-actions align="right">
        <span class="q-mr-md text-grey-7">已选 {{ selected.length }} 条</span>
        <q-btn
          color="primary"
          icon="playlist_add"
          label="逐条创建并入队"
          :disable="!selected.length"
          :loading="submitting"
          @click="submit"
        />
      </q-card-actions>
    </q-card>

    <template v-if="result">
      <div class="text-subtitle1 q-mb-sm">
        入队结果：共 {{ result.total }} 条 ·
        <span class="text-positive">{{ result.succeeded }} 成功</span> ·
        <span :class="result.failed ? 'text-negative' : 'text-grey-7'">{{ result.failed }} 失败</span>
      </div>
      <q-markup-table flat bordered class="batch-result-table">
        <thead>
          <tr>
            <th class="text-left">样例 ID</th>
            <th class="text-left">样例名称</th>
            <th class="text-left">结果</th>
            <th class="text-left">新作业 / 原因</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in result.items" :key="item.sample_id">
            <td>{{ item.sample_id }}</td>
            <td>{{ item.sample_name || '—' }}</td>
            <td>
              <q-badge :color="item.success ? 'positive' : 'negative'">
                {{ item.success ? '成功' : '失败' }}
              </q-badge>
            </td>
            <td>
              <router-link v-if="item.success" :to="`/jobs/${item.job_id}`" class="text-primary">
                作业 #{{ item.job_id }}
              </router-link>
              <span v-else class="text-negative">{{ item.reason }}</span>
            </td>
          </tr>
        </tbody>
      </q-markup-table>

      <div class="q-mt-md">
        <q-btn flat color="primary" label="查看作业历史" to="/jobs" />
      </div>
    </template>
  </q-page>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { createJobsBatch, listSamples } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const $q = useQuasar()
const loading = ref(false)
const submitting = ref(false)
const rows = ref([])
const selected = ref([])
const result = ref(null)

const columns = [
  { name: 'id', label: 'ID', field: 'id', align: 'left' },
  { name: 'name', label: '名称', field: 'name', align: 'left' },
  { name: 'description', label: '说明', field: 'description', align: 'left' },
  { name: 'is_broken', label: '状态', field: 'is_broken', align: 'left' },
]

async function load() {
  loading.value = true
  try {
    rows.value = await listSamples()
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '加载失败' })
  } finally {
    loading.value = false
  }
}

async function submit() {
  if (!selected.value.length) {
    $q.notify({ type: 'warning', message: '请先勾选样例' })
    return
  }
  submitting.value = true
  try {
    const ids = selected.value.map((s) => s.id)
    result.value = await createJobsBatch(ids)
    selected.value = []
    if (result.value.failed === 0) {
      $q.notify({ type: 'positive', message: `${result.value.succeeded} 条全部入队成功` })
    } else {
      $q.notify({
        type: 'warning',
        message: `${result.value.succeeded} 成功 / ${result.value.failed} 失败,详见结果表`,
      })
    }
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '批量入队失败' })
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>
