# Bybit Exchange Metadata

`src/leonardo/connection/exchange/metadata/bybit.exchange.json` is the first
Leonardo V2 exchange metadata file. It records static Bybit capability facts for
future catalog loading and preflight decisions.

This phase adds metadata only. It does not implement a REST client, WebSocket
client, exchange adapter, metadata loader, catalog population, credential
handling, storage writer, Core behavior, GUI behavior, or Runtime Manager
behavior.

## Policy Source

The metadata preserves the Bybit policy values accepted for this V2 phase:

- exchange/provider id: `bybit`
- supported regular OHLCV markets: `spot`, `linear`, `inverse`
- known deferred market: `options`, mapped to Bybit category `option`
- V5 kline endpoint: `GET /v5/market/kline`
- public REST mainnet base: `https://api.bybit.com`
- alternate REST mainnet base: `https://api.bytick.com`
- public REST testnet base: `https://api-testnet.bybit.com`
- public WebSocket mainnet base: `wss://stream.bybit.com/v5/public`
- public WebSocket testnet base: `wss://stream-testnet.bybit.com/v5/public`

The old-version exchange reference also used Bybit markets `spot`, `linear`,
`inverse`, and `option`, plus the alias `60m -> 1h`. Those concepts are
preserved as metadata facts only. No old module is copied into V2.

## Markets

Regular OHLCV Download Data v1 supports:

- `spot`
- `linear`
- `inverse`

The `options` canonical market is included as known but unsupported for regular
OHLCV Download Data v1. It maps to Bybit API category `option`, which belongs to
instruments metadata and later option-specific scope rather than the current
`/v5/market/kline` regular OHLCV policy.

## Timeframes

The metadata declares these canonical timeframes:

- `1m`, `3m`, `5m`, `15m`, `30m`
- `1h`, `2h`, `4h`, `6h`, `12h`
- `1d`, `1w`, `1M`

Provider interval mapping:

- `1m -> 1`
- `3m -> 3`
- `5m -> 5`
- `15m -> 15`
- `30m -> 30`
- `1h -> 60`
- `2h -> 120`
- `4h -> 240`
- `6h -> 360`
- `12h -> 720`
- `1d -> D`
- `1w -> W`
- `1M -> M`

Alias:

- `60m -> 1h`

The monthly `1M` value is retained exactly in metadata. A later loader/catalog
phase must decide how monthly intervals map into provider capability contracts
without confusing `1M` with minute-based `1m`.

## Kline Policy

The kline policy records:

- endpoint: `/v5/market/kline`
- method: `GET`
- category values: `spot`, `linear`, `inverse`
- symbol form: uppercase, for example `BTCUSDT`
- timestamp units: milliseconds
- default limit: `200`
- max limit: `1000`
- response order: reverse by `startTime`
- expected future adapter normalization: ascending by candle open time before
  storage

## WebSocket Policy

The public kline topic template is:

```text
kline.{interval}.{symbol}
```

The metadata records public kline push frequency as `1-60s` and the closed
candle indicator as `confirm=true`. Historical Download Data does not require
WebSocket transport by default.

## Future Work

A later phase may add a pure loader that converts this static JSON into
`DownloadProviderCapability` values and then populates `DownloadCapabilityCatalog`.
That phase must remain separate from adapter/client execution and must handle
the `1M` monthly interval deliberately.
