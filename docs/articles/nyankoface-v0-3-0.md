---
title: Make every transition legible
type: article
description: How NyankoFace v0.3.0 improves discovery, navigation feedback, Space readiness, code reading, and identity.
readingTime: 6 minutes
tags: [release, performance, spaces, discovery]
---

![NyankoFace v0.3.0 release header](/releases/release-header-v0.3.0.svg)

# Make every transition legible

Performance is not only the time until the last component finishes. It is also whether the interface acknowledges a tap, preserves the user's sorting choice, explains that an app is still starting, and keeps familiar navigation and identity across surfaces. NyankoFace v0.3.0 treats that entire path as one product concern.

## Find the right repository before opening it

Created, updated, likes, and views now sort the complete matching set across 11 catalogs before pagination. Stable tie breakers keep repeated requests deterministic, while URL parameters make a filtered and sorted view shareable. Metrics are fetched in bounded batches instead of one request per card.

## Respond before the destination is ready

Navigation now separates immediate feedback from completed content. Pressed controls and a progress indicator acknowledge intent; route skeletons preserve layout; a 15-second timeout provides a retry rather than indefinite waiting. Public knowledge metadata may use a short in-process cache with in-flight coalescing, but private and authenticated content never enters it.

## Show the Space lifecycle, not a blank frame

The Space repository shell arrives before the container. One runtime state source drives the badge and app panel, and the runner endpoint is probed every 750 ms before the iframe mounts. In local ten-run comparisons, candidate p50 fell from about 358–359 ms to 67 ms. The p95 remained near baseline because occasional roughly 360 ms outliers still exist; the release does not hide that tail.

## Keep code and controls recognizable

Server-side syntax highlighting removes the need for a client highlighting runtime and maps tokens into Standard, Solarpunk, and Cyberpunk themes. Unknown languages fall back safely. Portal and Forgejo navigation now share a versioned contract, and one canonical cat mark identifies the platform from favicon to documentation.

The result is not a claim that every request became five times faster. It is a system that reports intent quickly, measures bounded route classes, exposes runtime phases, and documents where local evidence ends.

Continue with the [full v0.3.0 release notes](../guide/releases/v0.3.0.md), [navigation performance](../guide/performance.md), or [catalog metric sorting](../guide/catalog-metric-sorting.md).
