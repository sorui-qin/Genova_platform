<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <h4 :class="cn('text-sm font-semibold text-foreground', props.class)">
    <slot />
  </h4>
</template>
