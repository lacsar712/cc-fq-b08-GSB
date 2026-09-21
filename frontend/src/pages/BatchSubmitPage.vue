<template>
  <q-page class="page-pad">
    <div class="row items-center q-mb-md">
      <div class="text-h5">批量入队</div>
      <q-space />
      <q-btn flat icon="refresh" label="刷新" @click="load" :loading="loading" />
      <q-btn
        color="primary"
        class="q-ml-sm"
        :label="`批量入队（${selected.length}）`"
        :disable="selected.length === 0"
        :loading="submitting"
        @click="submit"
      />
    </div>

    <q-banner v-if="auth.role !== 'bioops'" class="bg-warning text-dark q-mb-md" rounded>
      审计员不可提交作业，请使用 bioops 账号。
    </q-banner>

    <q-table
      v-model:selected="selected"
      flat
      bordered
      row-key="id"
      selection="multiple"
      :rows="rows"
      :columns="columns"
      :loading="loading"
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

    <q-card v-if="results.length" flat bordered class="q-mt-md">
      <q-card-section>
        <div class="text-subtitle1 q-mb-sm">
          入队结果：成功 {{ okCount }} 条 / 失败 {{ failCount }} 条
        </div>
        <q-list dense separator>
          <q-item v-for="r in results" :key="r.sample_id">
            <q-item-section avatar>
              <q-icon
                :name="r.ok ? 'check_circle' : 'error'"
                :color="r.ok ? 'positive' : 'negative'"
              />
            </q-item-section>
            <q-item-section>{{ r.sample_name }}</q-item-section>
            <q-item-section side>
              <q-btn
                v-if="r.ok"
                dense
                flat
                color="primary"
                :label="`作业 #${r.job_id}`"
                :to="`/jobs/${r.job_id}`"
              />
              <span v-else class="text-negative">{{ r.reason }}</span>
            </q-item-section>
          </q-item>
        </q-list>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn flat color="primary" label="查看作业历史" to="/jobs" />
      </q-card-actions>
    </q-card>
  </q-page>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useQuasar } from 'quasar'
import { createJobsBatch, listSamples } from '../api/client'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const $q = useQuasar()
const loading = ref(false)
const submitting = ref(false)
const rows = ref([])
const selected = ref([])
const results = ref([])

const columns = [
  { name: 'id', label: 'ID', field: 'id', align: 'left' },
  { name: 'name', label: '名称', field: 'name', align: 'left' },
  { name: 'description', label: '说明', field: 'description', align: 'left' },
  { name: 'is_broken', label: '状态', field: 'is_broken', align: 'left' },
]

const okCount = computed(() => results.value.filter((r) => r.ok).length)
const failCount = computed(() => results.value.filter((r) => !r.ok).length)

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
  results.value = []
  try {
    const data = await createJobsBatch(selected.value.map((s) => s.id))
    results.value = data.results
    $q.notify({
      type: failCount.value ? 'warning' : 'positive',
      message: `批量入队完成:成功 ${okCount.value} 条,失败 ${failCount.value} 条`,
    })
    selected.value = []
  } catch (e) {
    $q.notify({ type: 'negative', message: e.message || '批量入队失败' })
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>
