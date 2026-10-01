<template>
  <ModulePage :meta="meta" />
</template>

<script setup lang="ts">
import ModulePage from '@/components/ModulePage.vue'
import { moduleMeta } from '@/modules'

const meta = moduleMeta('pressurevessel')
</script>
