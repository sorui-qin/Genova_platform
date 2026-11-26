<template>
  <section class="space-y-3 rounded-lg border border-blue-200 bg-white p-3" data-testid="pose-preparation-card">
    <div>
      <h4 class="font-semibold">{{ L('姿态准备参数','Pose preparation parameters') }}</h4>
    </div>
    <dl class="grid gap-x-4 gap-y-2 text-sm sm:grid-cols-2">
      <div>
        <dt class="text-xs text-slate-500">{{ L('来源生成任务','Source generation job') }}</dt>
        <dd class="mt-1 break-all font-mono text-xs">{{ draft.source_job_id || '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('结果 / 分子','Result / molecule') }}</dt>
        <dd class="mt-1 break-all">{{ draft.result_id || '—' }} · {{ draft.molecule_id || '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('输入种子','Input seed') }}</dt>
        <dd class="mt-1 break-all font-mono text-xs">{{ draft.seed_dataset_id || '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('Protein Context','Protein Context') }}</dt>
        <dd class="mt-1 break-all font-mono text-xs">{{ effective.protein_context_id || contextId || '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('处理范围','Scope') }}</dt>
        <dd class="mt-1">{{ effective.scope?.kind === 'single_molecule' ? L('单分子 · 1 条记录','Single molecule · 1 record') : effective.scope || '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('固定流程','Fixed workflow') }}</dt>
        <dd class="mt-1">TarPass · {{ L('构象生成 → 对接','conformer generation → docking') }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('姿态 / 来源序号','Pose / source index') }}</dt>
        <dd class="mt-1">{{ draft.pose || 'docked' }} · {{ draft.source_index ?? '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('协议版本','Protocol version') }}</dt>
        <dd class="mt-1 break-all font-mono text-xs">{{ draft.protocol_version || effective.protocol_version || '—' }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('性质预筛','Property prefilters') }}</dt>
        <dd class="mt-1">{{ effective.prefilters?.length ? effective.prefilters.length : L('无','None') }}</dd>
      </div>
      <div>
        <dt class="text-xs text-slate-500">{{ L('关键相互作用','Key interactions') }}</dt>
        <dd class="mt-1">{{ effective.key_interactions?.length ? effective.key_interactions.length : L('无','None') }}</dd>
      </div>
    </dl>
    <p v-if="!approvalReady" role="alert" class="rounded border border-amber-200 bg-amber-50 p-2 text-sm text-amber-800">{{ L('请重新核对当前分子的姿态准备参数。','Review the pose preparation parameters for the current molecule again.') }}</p>
    <div class="flex flex-wrap items-center gap-2 border-t pt-3">
      <Button v-if="approvalReady" :disabled="busy" @click="$emit('approve')">{{ L('确认参数并准备姿态','Approve parameters and prepare pose') }}</Button>
      <Button v-else :disabled="busy" @click="$emit('recheck')">{{ L('重新核对当前参数','Recheck current parameters') }}</Button>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Button } from '@/components/ui/button'

const props = defineProps<{
  draft: Record<string, any>
  contextId?: string
  busy: boolean
}>()
defineEmits<{ approve: []; recheck: [] }>()

const effective = computed(() => props.draft.effective_postprocessing || {})
const approvalReady = computed(() => /^[0-9a-f]{64}$/.test(String(props.draft.approval_hash || '')))

const { locale } = useI18n()
const L = (zh: string, en: string) => locale.value.startsWith('zh') ? zh : en
</script>
