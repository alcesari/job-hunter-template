# Mappa campi piattaforme — LinkedIn / Indeed

Mappature dai campi dell'**intento** di ricerca (`searches/<intent-id>.yaml`, più i `defaults` ereditati) ai campi delle due piattaforme. I nomi di menu/filtri sono quelli tipici delle interfacce; possono variare per lingua dell'account e per aggiornamenti delle piattaforme — trattali come indicazioni del CONCETTO, non come nomi garantiti.

## LinkedIn (ricerca lavoro + "Crea avviso di offerte")

| Campo intento | Campo LinkedIn | Come compilarlo |
|---|---|---|
| `ruoli_target.titolo_principale` + `sinonimi` | Barra di ricerca (parole chiave) | La ricerca LinkedIn supporta operatori booleani: `"Data Engineer" OR "Analytics Engineer"`. Virgolette sui titoli multi-parola. Max ~2-3 titoli per query, oltre la query perde precisione: meglio due alert. |
| `location_target.area` | Campo Località | Città o paese. Per aree tipo "Remote Europe" usa "Unione europea" o il paese + filtro Remoto. |
| `location_target.accetta_remoto/ibrido` | Filtro "In sede/Remoto/Ibrido" | Spunta le modalità accettate. Se `accetta_remoto: true` e `accetta_ibrido: true`: spunta Remoto + Ibrido + In sede (l'annuncio in sede nella location target resta valido). |
| `seniority.livello` | Filtro "Livello di esperienza" | `junior` → Junior/Entry level; `medio` → Medio livello (Associate/Mid-Senior level); `senior` → Mid-Senior level; `lead` → Direttore no, Mid-Senior sì (i titoli lead spesso non hanno livello dedicato). Il filtro LinkedIn è impreciso: dillo all'utente, la routine rifiltra a valle. |
| `parametri_esecuzione.finestra_temporale_ore` | Filtro "Data di pubblicazione" | "Ultime 24 ore" per la ricerca manuale; per l'ALERT non serve (l'alert manda solo annunci nuovi per costruzione). |
| — | Impostazioni avviso | Frequenza: Giornaliera. Canale: Email (obbligatorio: la routine legge da Gmail). |

### URL pre-filtrato + `geoId` (chiave canonica dell'alert)

Invece di far impostare i filtri a mano, **costruisci l'URL di ricerca già filtrato** e fallo aprire all'utente (poi "Crea avviso"). Template:

```
https://www.linkedin.com/jobs/search/?keywords=<KEYWORDS>&geoId=<GEOID>[&f_E=<LIVELLI>][&f_WT=<MODALITA>]
```

- `keywords`: la stessa stringa booleana della barra (URL-encoded), es. `"Backend Developer" OR "Java Developer"`.
- `geoId`: identificatore area LinkedIn (tabella sotto). È — con `keywords` — la **chiave canonica** `<keywords-slug>:<geoId>` che il registro (`searches/alerts-registry.yaml`) e la routine usano per attribuire gli annunci alla ricerca giusta (vedi `references/alerts-registry.schema.yaml` e `job-watch/SKILL.md`, sezione «Attribuzione alert → ricerca»).
- `f_E` (livello esperienza): `2`=Entry, `3`=Associate, `4`=Mid-Senior, `5`=Director, `6`=Executive (mappa da `seniority.livello`; `medio` → `3,4`). `f_WT` (modalità): `1`=In sede, `2`=Remoto, `3`=Ibrido.
- Escludi SEMPRE dalla chiave i parametri **volatili**: `f_TPR`, `trk`, `lipi`, `midToken`, `eid` (cambiano a ogni email/sessione).

| Area (`location_target.area`) | `geoId` | Note |
|---|---|---|
| Italia | `103350119` | verificato |
| Milano | `90009936` | verificato |
| Unione Europea / Remote EU | `91000000` | verificato ("European Union") |
| Germania | `101282230` | da doc D.1 |
| Spagna | `105646813` | da doc D.1 |
| Paesi Bassi | `102890719` | da doc D.1 |
| Belgio | `100565514` | da doc D.1 |
| Francia | `105015875` | da doc D.1 |
| Regno Unito | `101165590` | da doc D.1 |

Area non in tabella: fai fare all'utente una ricerca su LinkedIn per quell'area e incolla l'URL una volta sola (il `geoId` è nel querystring) → aggiungilo qui.

Note LinkedIn:
- L'avviso si crea dal toggle "Crea avviso di offerte" che appare sulla pagina dei risultati di ricerca, dopo aver impostato query + filtri.
- Gli avvisi si gestiscono da "Offerte di lavoro" → "Avvisi offerte di lavoro" (lì si eliminano quelli vecchi dopo una modifica del profilo).
- Le email di alert arrivano da `jobs-noreply@linkedin.com`. Alcuni formati di alert contengono più annunci per email e NON contengono descrizione: comportamento noto, gestito dalla routine.

## Indeed (ricerca + "Attiva avvisi email" / "Le mie ricerche")

| Campo intento | Campo Indeed | Come compilarlo |
|---|---|---|
| `ruoli_target.titolo_principale` + `sinonimi` | Campo "Cosa" (parole chiave) | Indeed supporta sintassi tipo `title:(data engineer)` e OR nelle parole chiave, ma il comportamento varia per dominio nazionale: la via robusta è UN titolo per alert. I sinonimi molto vicini (es. "BI Developer"/"Business Intelligence Developer") si possono unire con OR. |
| `location_target.area` | Campo "Dove" | Città o paese. Per il remoto: parola chiave "remote" nel Dove o filtro "Da remoto" dove presente. Attenzione al dominio nazionale: it.indeed.com per l'Italia, nl.indeed.com per i Paesi Bassi, ecc. — l'alert va creato sul dominio del paese target. |
| `seniority` | — | Indeed non ha un filtro seniority affidabile a livello alert: NON promettere il filtro, la routine rifiltra a valle. |
| — | Attivazione avviso | Dopo la ricerca, usa "Ricevi aggiornamenti via email per questa ricerca" (o toggle equivalente) inserendo l'indirizzo Gmail collegato. Frequenza: giornaliera. |

Note Indeed:
- Le email di alert arrivano da mittenti tipo `alert@indeed.com` (il dominio esatto può variare per paese: la routine cerca per mittente Indeed in generale).
- La routine usa anche la RICERCA DIRETTA Indeed via connettore: gli alert Indeed sono una fonte integrativa, non l'unica. Se il numero di alert da creare è alto, dai precedenza agli alert LinkedIn (per Indeed la ricerca diretta copre già i ruoli principali).

## Cosa NON è mappabile su nessuna delle due piattaforme (filtri a valle, li applica la routine)

- `esclusioni.titoli_da_escludere` (Head of, Director, VP, C-level)
- `esclusioni.tipo_contratto_da_escludere` (Internship, Traineeship, Stage)
- `lingue_annuncio.*` (lingua prevalente del corpo, requisiti linguistici obbligatori)
- `settori.esclusi`
