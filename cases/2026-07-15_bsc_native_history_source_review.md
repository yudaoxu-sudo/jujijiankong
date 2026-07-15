# BSC Native-History Source Review

Date: 2026-07-15

## Goal

Find a credential-free indexed source for inbound native-BNB transfers before each report-only CEX-withdrawal recipient's anchor block. The source would support `common_gas_source_ratio` without scanning hundreds of full BSC blocks during the five-minute monitor cycle.

## Acceptance Requirements

- BSC mainnet / chain ID `56` is explicitly supported by the provider.
- Results expose transaction hash, block number, transaction index, sender, recipient, native value, and success state.
- Queries support a bounded end block, deterministic pagination, and an explicit coverage boundary.
- The monitor can keep total enrichment latency near four seconds and retry progressively without delaying core alerts.
- A negative result is usable only after every required page in the requested block window completes.
- Common funding remains coordination evidence. It cannot change `direction=unknown`, `action=Observe`, Telegram ranking, or trade signals.

## Reviewed Sources

### Etherscan V2 / BscScan

- BscScan has migrated to the unified Etherscan V2 API: [V2 migration](https://docs.etherscan.io/v2-migration).
- BNB Smart Chain mainnet is chain ID `56`, with access marked Paid Tier in the [supported-chains table](https://docs.etherscan.io/supported-chains).
- `account/txlist` supplies top-level normal transactions and supports `startblock`, `endblock`, `page`, `offset`, and `sort`: [txlist](https://docs.etherscan.io/api-reference/endpoint/txlist).
- Contract-internal native transfers require the separate [txlistinternal](https://docs.etherscan.io/api-reference/endpoint/txlistinternal) query.
- A no-key chain-56 probe returned HTTP 200 with an application-level rejection stating that free access is unavailable for this chain. A chain-1 control probe rejected the missing API key.

Decision: `blocked_paid_api_key`. This becomes viable only after a read-only paid Etherscan key is supplied through ignored local/server secret stores. Top-level and internal coverage must remain separate.

### Routescan

- The official Etherscan-compatible live endpoint was queried for chain `56` with `txlist`, bounded pagination parameters, and no API key: [official live probe](https://api.routescan.io/v2/network/mainnet/evm/56/etherscan/api?module=account&action=txlist&address=0x0000000000000000000000000000000000001000&startblock=0&endblock=99999999&page=1&offset=1&sort=desc).
- HTTP succeeded, while the application response reported `chain not supported` and returned no result.

Decision: `blocked_chain_56_unsupported`.

### Blockscout

- Blockscout's legacy account API can expose address normal transactions with block bounds and optional API keys: [account txlist](https://docs.blockscout.com/api-reference/account/get-a-list-of-transactions-by-address).
- Its v2 address endpoint exposes direction filters and cursor pagination: [address transactions](https://docs.blockscout.com/api-reference/get-address-transactions).
- The [PRO supported-networks table](https://docs.blockscout.com/devs/pro-api) does not list BNB Smart Chain mainnet.
- The official Chainscout registry live response had no top-level chain ID `56` entry in the 2026-07-15 probe. BNB Chain's own [wallet configuration](https://docs.bnbchain.org/bnb-smart-chain/developers/wallet-configuration/) points mainnet users to BscScan.

Decision: `blocked_no_verified_official_bsc_instance`.

## Runtime Decision

No reviewed source satisfies the credential-free chain-56 acceptance requirements. The runtime keeps `common_gas_source_ratio=null` and `common_gas_source` inside `unresolved_gates`. Full-block native-transaction scanning remains excluded from the withdrawal path because its cost and negative-evidence quality do not fit the five-minute monitor.

Resume this unit when one of these conditions is met:

1. an official no-key BSC index exposes bounded address history and passes latency, pagination, and coverage tests;
2. the user supplies a paid read-only Etherscan key through ignored secret stores;
3. an existing approved warehouse returns complete `{hash, block, transaction_index, from, to, value, status}` rows for the candidate window.
