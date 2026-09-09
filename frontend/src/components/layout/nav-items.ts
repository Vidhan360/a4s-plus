import {
  Activity,
  BarChart3,
  Boxes,
  Cpu,
  Layers,
  Map,
  Radar,
  ScrollText,
  Settings2,
  ShieldAlert,
  Siren,
  Users,
} from 'lucide-react';

import type * as React from 'react';

import { PERM } from '@/lib/constants';

export interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  /** Any one of these permissions is enough to see the entry. */
  permissions: string[];
  description: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: 'Operations',
    items: [
      {
        href: '/dashboard',
        label: 'Command dashboard',
        icon: Activity,
        permissions: [PERM.dashboardRead],
        description: 'Live roster risk, alerts and swarm state',
      },
      {
        href: '/personnel',
        label: 'Personnel',
        icon: Users,
        permissions: [PERM.personnelRead],
        description: 'Roster, vitals history and digital twins',
      },
      {
        href: '/alerts',
        label: 'Alerts',
        icon: Siren,
        permissions: [PERM.alertRead],
        description: 'Deduplicated alert queue and escalation',
      },
      {
        href: '/simulation',
        label: 'Simulation',
        icon: Layers,
        permissions: [PERM.simulationRead],
        description: 'Scenario engine, seed and speed control',
      },
    ],
  },
  {
    title: 'Terrain & assets',
    items: [
      {
        href: '/terrain',
        label: 'Terrain',
        icon: Map,
        permissions: [PERM.terrainRead],
        description: 'Synthetic elevation and hazard layers',
      },
      {
        href: '/routes',
        label: 'Safe routing',
        icon: Radar,
        permissions: [PERM.terrainRead],
        description: 'A* hazard-aware evacuation planning',
      },
      {
        href: '/uav',
        label: 'UAV swarm',
        icon: Boxes,
        permissions: [PERM.droneRead],
        description: 'Simulated swarm telemetry and formations',
      },
    ],
  },
  {
    title: 'Assurance',
    items: [
      {
        href: '/analytics',
        label: 'Analytics & models',
        icon: BarChart3,
        permissions: [PERM.analyticsRead],
        description: 'Measured model comparison and trends',
      },
      {
        href: '/security',
        label: 'Security monitor',
        icon: ShieldAlert,
        permissions: [PERM.securityRead],
        description: 'Real controls and simulated attack drills',
      },
      {
        href: '/audit',
        label: 'Audit trail',
        icon: ScrollText,
        permissions: [PERM.auditRead],
        description: 'Append-only record of privileged actions',
      },
    ],
  },
  {
    title: 'Administration',
    items: [
      {
        href: '/admin/users',
        label: 'Users & roles',
        icon: Users,
        permissions: [PERM.userRead],
        description: 'Accounts, roles and lockout state',
      },
      {
        href: '/admin/config',
        label: 'Runtime config',
        icon: Settings2,
        permissions: [PERM.configRead],
        description: 'Risk, alert and routing parameters',
      },
      {
        href: '/admin/system',
        label: 'System health',
        icon: Cpu,
        permissions: [PERM.simulationRead],
        description: 'Subsystem status and model registry',
      },
    ],
  },
];
