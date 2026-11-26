<template>
  <div class="flex min-h-40 flex-col items-center justify-center gap-3 p-6 text-center" :role="kind === 'error' ? 'alert' : 'status'">
    <component :is="kind === 'loading' ? LoaderCircle : kind === 'error' ? CircleAlert : kind === 'success' ? CircleCheck : Inbox" class="h-6 w-6" :class="kind === 'loading' ? 'animate-spin text-primary' : kind === 'error' ? 'text-destructive' : 'text-muted-foreground'" aria-hidden="true" />
    <p class="font-medium">{{ title }}</p>
    <p v-if="description" class="max-w-lg text-sm text-muted-foreground">{{ description }}</p>
    <slot />
  </div>
</template>
<script setup lang="ts">
import { CircleAlert, CircleCheck, Inbox, LoaderCircle } from 'lucide-vue-next'
withDefaults(defineProps<{ kind?: 'loading' | 'empty' | 'error' | 'success'; title: string; description?: string }>(), { kind: 'empty' })
</script>
