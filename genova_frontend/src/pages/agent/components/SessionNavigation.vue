<template>
  <aside class="flex min-h-0 flex-col gap-3 rounded-xl border bg-white p-3">
    <div class="flex items-center justify-between gap-2"><span class="text-sm font-medium">{{ t('agent.ui.history') }}</span><Button size="sm" variant="ghost" @click="$emit('collapse')">‹</Button></div>
    <Button :disabled="busy" @click="$emit('create')">+ {{ t('agent.session.newSession') }}</Button>
    <nav class="min-h-0 flex-1 space-y-1 overflow-y-auto" :aria-label="t('agent.ui.history')"><button v-for="item in history" :key="item.id" class="block w-full truncate rounded-lg px-3 py-2 text-left text-sm hover:bg-slate-50" :class="item.id === current ? 'bg-blue-50 text-blue-800' : 'text-slate-600'" :disabled="busy && !switching" :title="item.goal" @click="$emit('restore', item.id)">{{ item.goal || t('agent.session.newSession') }}</button></nav>
  </aside>
</template>
<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'
const { t } = useI18n()
defineProps<{ history: Array<{id:string; goal:string}>; current?:string; busy:boolean; switching?:boolean }>()
defineEmits<{ create:[]; restore:[id:string]; collapse:[] }>()
</script>
