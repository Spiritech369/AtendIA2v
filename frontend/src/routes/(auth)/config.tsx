import { createFileRoute } from "@tanstack/react-router";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BrandFactsEditor } from "@/features/config/components/BrandFactsEditor";
import { FollowupsConfigEditor } from "@/features/config/components/FollowupsConfigEditor";
import { IntegrationsTab } from "@/features/config/components/IntegrationsTab";
import { NLUConfigEditor } from "@/features/config/components/NLUConfigEditor";
import { QosConfigEditor } from "@/features/config/components/QosConfigEditor";
import { RunnerRulesEditor } from "@/features/config/components/RunnerRulesEditor";
import { ToneEditor } from "@/features/config/components/ToneEditor";
import { requireRole } from "@/lib/auth-guards";

export const Route = createFileRoute("/(auth)/config")({
  beforeLoad: requireRole(["tenant_admin", "superadmin"]),
  component: ConfigPage,
});

// Pipeline editing lives on `/pipeline`; Configuracion keeps tenant-level
// controls such as decision rules, tone, NLU, followups and integrations.
function ConfigPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Configuración</h1>
      <Tabs defaultValue="runner-rules">
        <TabsList>
          <TabsTrigger value="brand-facts">Brand facts</TabsTrigger>
          <TabsTrigger value="qos">QoS</TabsTrigger>
          <TabsTrigger value="followups">Seguimientos</TabsTrigger>
          <TabsTrigger value="tone">Tono</TabsTrigger>
          <TabsTrigger value="nlu">NLU</TabsTrigger>
          <TabsTrigger value="runner-rules">Motor de decisión</TabsTrigger>
          <TabsTrigger value="integrations">Integraciones</TabsTrigger>
        </TabsList>
        <TabsContent value="brand-facts" className="mt-4">
          <BrandFactsEditor />
        </TabsContent>
        <TabsContent value="qos" className="mt-4">
          <QosConfigEditor />
        </TabsContent>
        <TabsContent value="followups" className="mt-4">
          <FollowupsConfigEditor />
        </TabsContent>
        <TabsContent value="tone" className="mt-4">
          <ToneEditor />
        </TabsContent>
        <TabsContent value="nlu" className="mt-4">
          <NLUConfigEditor />
        </TabsContent>
        <TabsContent value="runner-rules" className="mt-4">
          <RunnerRulesEditor />
        </TabsContent>
        <TabsContent value="integrations" className="mt-4">
          <IntegrationsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
