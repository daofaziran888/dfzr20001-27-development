<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">茶庄园品控溯源系统</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">制茶师、品控员和庄园主协作管理茶园地块、制茶工序与溯源链条，确保每一批次茶叶从鲜叶到成品全程可追溯。</span>
        <span class="head-user">当前值班：应用开发组</span>
      </header>
      <RouterView :key="$route.path" />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "茶园地块", path: "/tea_garden" }, { label: "鲜叶采摘", path: "/picking" }, { label: "萎凋工序", path: "/withering" }, { label: "杀青工序", path: "/fixing" }, { label: "揉捻工序", path: "/rolling" }, { label: "发酵工序", path: "/fermentation" }, { label: "缺测核验单", path: "/gap_check" }, { label: "干燥工序", path: "/drying" }, { label: "精制分级", path: "/grading" }, { label: "拼配配方", path: "/blending" }, { label: "包装规格", path: "/packing" }, { label: "仓储养护", path: "/storage" }, { label: "检测报告", path: "/testing" }, { label: "认证资质", path: "/certification" }, { label: "溯源码段", path: "/trace_code" }, { label: "发运交接", path: "/shipment" }, { label: "样品留样", path: "/sample" }, { label: "不合格处置", path: "/defect" }, { label: "内审巡查", path: "/audit" }]
</script>
