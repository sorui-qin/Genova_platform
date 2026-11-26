<template>
  <div class="space-y-2 rounded-lg border border-slate-200 bg-white p-3">
    <Label>{{ $t('platform.proteinContextLabel') }}</Label>
    <input v-model="search" type="search" maxlength="200" :aria-label="$t('platform.search')" :placeholder="$t('platform.search')" class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm" />
    <select
      class="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
      :value="modelValue"
      :aria-label="$t('platform.proteinContextLabel')"
      :disabled="loading"
      @change="selectContext(($event.target as HTMLSelectElement).value)"
    >
      <option value="">{{ loading ? $t('platform.loading') : $t('platform.selectAPreparedContext') }}</option>
      <option v-if="modelValue && !contexts.some(item => item.id === modelValue)" :value="modelValue">{{ context?.id === modelValue ? context.name : selectedContext?.id === modelValue ? selectedContext.name : modelValue }}</option>
      <option v-for="item in contexts" :key="item.id" :value="item.id" :disabled="!item.ready">
        {{ item.name }}{{ item.ready ? '' : ' · ' + $t('platform.structureNotReady') }}
      </option>
    </select>
    <div v-if="page || hasMore" class="flex items-center gap-2">
      <Button size="sm" variant="outline" :disabled="loading || page === 0" @click="changePage(page - 1)">{{ $t('platform.previous') }}</Button>
      <span class="text-xs">{{ page + 1 }}</span>
      <Button size="sm" variant="outline" :disabled="loading || !hasMore" @click="changePage(page + 1)">{{ $t('platform.next') }}</Button>
    </div>
    <slot />
    <slot name="actions"><div class="flex flex-wrap gap-2">
      <Button size="sm" variant="outline" @click="$emit('create')">{{ $t('platform.createProteinContext') }}</Button>
      <Button v-if="modelValue" size="sm" variant="outline" @click="$emit('edit')">{{ $t('platform.editReprepare') }}</Button>
    </div></slot>
    <p v-if="!loading && !contexts.length" class="text-xs text-slate-500">{{ $t('platform.noPreparedProteinContextYet') }}</p>
  </div>
</template>

<script setup lang="ts">
import { translate } from '@/i18n'

import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { listProteinContexts } from '@/api/proteinContext'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import type { ProteinContext, ProteinContextListItem } from '@/types/proteinContext'
import { displayErrorMessage } from '@/utils/requestError'

const props = defineProps<{ modelValue: string; context?: ProteinContext | null }>()
const emit = defineEmits<{
  select: [id: string, context?: ProteinContextListItem]
  create: []
  edit: []
  error: [message: string]
}>()
const contexts = ref<ProteinContextListItem[]>([])
const selectedContext = ref<ProteinContextListItem | null>(null)
const loading = ref(false)
const search = ref(''), page = ref(0), hasMore = ref(false)
let controller: AbortController | undefined, revision = 0
let searchTimer: ReturnType<typeof setTimeout> | undefined

function selectContext(id: string) {
  selectedContext.value = contexts.value.find(item => item.id === id) || null
  emit('select', id, selectedContext.value || undefined)
}
async function load() {
  const current = ++revision
  controller?.abort(); controller = new AbortController()
  loading.value = true
  try {
    const result = (await listProteinContexts({ limit: 21, offset: page.value * 20, search: search.value.trim() || undefined, signal: controller.signal })).data
    if (current !== revision) return
    hasMore.value = result.length > 20
    contexts.value = result.slice(0, 20)
    const selected = contexts.value.find(item => item.id === props.modelValue)
    if (selected) selectedContext.value = selected
  } catch (error: any) {
    if (current !== revision) return
    emit('error', displayErrorMessage(error, translate('platform.failedToLoadProteinContexts')))
  } finally {
    if (current === revision) loading.value = false
  }
}
function changePage(value: number) { page.value = value; void load() }
watch(search, () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => changePage(0), 250) })
onMounted(load)
onBeforeUnmount(() => {
  revision++; controller?.abort(); clearTimeout(searchTimer)
})
</script>
