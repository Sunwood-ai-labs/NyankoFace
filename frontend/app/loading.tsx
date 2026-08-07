'use client';

import { usePathname } from 'next/navigation';
import {
  CatalogSkeleton,
  KnowledgeArticleSkeleton,
  KnowledgeListSkeleton,
  RepositorySkeleton,
} from '@/components/RouteSkeletons';
import { classifyNavigationRoute } from '@/lib/navigation-performance';

export default function RootLoading() {
  const route = classifyNavigationRoute(usePathname());
  if (route === 'knowledge-detail') return <KnowledgeArticleSkeleton />;
  if (route === 'knowledge-list') return <KnowledgeListSkeleton />;
  if (route === 'repository-detail') return <RepositorySkeleton />;
  return <CatalogSkeleton />;
}
