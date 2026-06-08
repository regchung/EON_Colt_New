<script setup>
import { useRoute } from 'vue-router'
import { computed } from 'vue'
import AppLayout from './components/AppLayout.vue'

const route = useRoute()
const useLayout = computed(() => route.meta.layout !== false)
</script>

<template>
  <AppLayout v-if="useLayout">
    <RouterView />
  </AppLayout>
  <RouterView v-else />
</template>
