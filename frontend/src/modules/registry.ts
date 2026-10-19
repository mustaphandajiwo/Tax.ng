// Every feature module, in one list. Adding a module = one import per surface.
import type { AppModule, SiteModule } from "./types";
import { appModule as academyApp } from "./academy/app";
import { siteModule as academySite } from "./academy/site";
import { appModule as advisoryApp } from "./advisory/app";
import { siteModule as advisorySite } from "./advisory/site";
import { appModule as billingApp } from "./billing/app";
import { siteModule as billingSite } from "./billing/site";
import { appModule as channelsApp } from "./channels/app";
import { siteModule as channelsSite } from "./channels/site";
import { appModule as complianceApp } from "./compliance/app";
import { siteModule as complianceSite } from "./compliance/site";
import { appModule as developerApp } from "./developer/app";
import { siteModule as developerSite } from "./developer/site";
import { appModule as einvoicingApp } from "./einvoicing/app";
import { siteModule as einvoicingSite } from "./einvoicing/site";
import { appModule as publishingApp } from "./publishing/app";
import { siteModule as publishingSite } from "./publishing/site";
import { appModule as workspaceApp } from "./workspace/app";
import { siteModule as workspaceSite } from "./workspace/site";

export const siteModules: SiteModule[] = [
  academySite,
  advisorySite,
  billingSite,
  channelsSite,
  complianceSite,
  developerSite,
  einvoicingSite,
  publishingSite,
  workspaceSite,
];

export const appModules: AppModule[] = [
  complianceApp,
  advisoryApp,
  workspaceApp,
  einvoicingApp,
  billingApp,
  developerApp,
  academyApp,
  publishingApp,
  channelsApp,
];
