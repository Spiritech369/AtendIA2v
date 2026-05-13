import { api } from "@/lib/api-client";

export type BaileysStatus =
  | "disconnected"
  | "connecting"
  | "qr_pending"
  | "connected"
  | "error";

export interface BaileysStatusResponse {
  status: BaileysStatus;
  phone: string | null;
  last_status_at: string;
  reason: string | null;
  prefer_over_meta: boolean;
}

export interface BaileysQRResponse {
  qr: string | null;
}

export const baileysApi = {
  status: async (): Promise<BaileysStatusResponse> =>
    (await api.get<BaileysStatusResponse>("/integrations/baileys/status")).data,
  connect: async (): Promise<BaileysStatusResponse> =>
    (await api.post<BaileysStatusResponse>("/integrations/baileys/connect")).data,
  disconnect: async (): Promise<BaileysStatusResponse> =>
    (await api.post<BaileysStatusResponse>("/integrations/baileys/disconnect")).data,
  qr: async (): Promise<BaileysQRResponse> =>
    (await api.get<BaileysQRResponse>("/integrations/baileys/qr")).data,
  setPreference: async (preferOverMeta: boolean): Promise<BaileysStatusResponse> =>
    (
      await api.patch<BaileysStatusResponse>(
        "/integrations/baileys/preference",
        { prefer_over_meta: preferOverMeta },
      )
    ).data,
};
