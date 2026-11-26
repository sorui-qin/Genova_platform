<template>
  <TwoStagePreparation v-bind="$props" @review-state="$emit('reviewState', $event)"><template v-if="$slots.assistant" #assistant><slot name="assistant" /></template></TwoStagePreparation>
</template>
<script setup lang="ts">
import TwoStagePreparation from './TwoStagePreparation.vue'
defineProps<{review?:Record<string,any>;selection?:Record<string,any>;reviewReadonly?:boolean}>()
defineEmits<{reviewState:[state:{dirty:boolean;valid:boolean;changes:Record<string,any>}]}>()
</script>
