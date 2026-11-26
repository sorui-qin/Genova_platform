<script lang="ts" setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import LanguageSwitcher from '@/components/common/LanguageSwitcher.vue'

const route = useRoute()
const router = useRouter()
const pageKey = computed(() => {
  if (['/molopt', '/molgen'].includes(route.path)) {
    const query = { ...route.query }
    delete query.engine
    delete query.protein_context_id
    return router.resolve({ path: route.path, query, hash: route.hash }).fullPath
  }
  return ['/molgen', '/postprocessing', '/protein-preparation'].includes(route.path) ? route.fullPath : route.path
})
const authPaths = ['/login', '/sign_up', '/forget_password', '/pswd_transit']

</script>

<template>
  <div v-if="authPaths.includes(route.path)" class="flex justify-end bg-white px-4 pt-3">
    <LanguageSwitcher />
  </div>
  <router-view :key="pageKey" />
</template>

<style>

</style>
