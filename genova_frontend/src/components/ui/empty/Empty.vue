<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div
    :class="
      cn(
        'flex w-full flex-col items-center justify-center bg-muted/40 px-6 py-10 text-center',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
