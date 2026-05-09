import { createFileRoute } from "@tanstack/react-router";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { BrandFactsEditor } from "@/features/config/components/BrandFactsEditor";
import { IntegrationsTab } from "@/features/config/components/IntegrationsTab";
import { PipelineEditor } from "@/features/config/components/PipelineEditor";
import { ToneEditor } from "@/features/config/components/ToneEditor";

export const Route = createFileRoute("/(auth)/config")({
  component: ConfigPage,
});

function ConfigPage() {
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight">Configuración</h1>
      <Tabs defaultValue="pipeline">
        <TabsList>
          <TabsTrigger value="pipeline">Pipeline</TabsTrigger>
          <TabsTrigger value="brand-facts">Brand facts</TabsTrigger>
          <TabsTrigger value="tone">Tono</TabsTrigger>
          <TabsTrigger value="integrations">Integraciones</TabsTrigger>
        </TabsList>
        <TabsContent value="pipeline" className="mt-4">
          <PipelineEditor />
        </TabsContent>
        <TabsContent value="brand-facts" className="mt-4">
          <BrandFactsEditor />
        </TabsContent>
        <TabsContent value="tone" className="mt-4">
          <ToneEditor />
        </TabsContent>
        <TabsContent value="integrations" className="mt-4">
          <IntegrationsTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
