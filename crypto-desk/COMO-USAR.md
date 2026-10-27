# Como usar o Crypto Antecipation Desk (guia para iniciante)

**Isto é um SIMULADOR.** Ele não compra nem vende nada de verdade. Use para aprender e testar.

## Ligar
1. Abra o terminal na pasta `crypto-desk`.
2. Rode: `./run.sh`. Na primeira vez ele instala tudo sozinho.
3. Abra o navegador em **http://localhost:8000**.
4. Com Docker: `cp .env.example .env` e depois `docker compose up -d --build`.

## As abas
- **Visão Geral:** preço, variação, nota de −100 (muito vendido) a +100 (muito comprado) e alertas.
- **Derivativos:** OI (dinheiro apostado em futuros), funding (quem paga quem) e long/short.
  Funding muito alto = todo mundo comprado = perigo de queda brusca.
- **Liquidações:** quem foi "estourado".
  O mapa de calor é uma **ESTIMATIVA** de onde há stops/liquidações acumulados. O preço costuma ser atraído para lá.
- **Baleias:** grandes transferências.
  Indo PARA a corretora = possível venda. SAINDO da corretora = acumulação.
- **Fluxo:** CVD (quem está agredindo, compradores ou vendedores), volume e book.
- **Narrativa/X:** notícias e posts importantes.
  **Nunca entre só por causa de uma notícia.** Espere o preço e o volume confirmarem.
- **Sinais:** o resumo de cada moeda, com direção, entrada, stop, alvos e o porquê.

## Alerta x Sinal
- 🟡 **Alerta de atenção:** "fique de olho". Não é para entrar.
- 🟢/🔴 **Sinal de entrada:** precisa de pelo menos 3 motivos independentes concordando.
  Mesmo assim, é simulado.

## Regras de ouro
- Arrisque no máximo 0,25% a 0,5% por operação.
- Alavancagem no máximo 3x.
- Perdeu 2 seguidas? Pare. O sistema pausa sozinho.
- Funding extremo = cuidado redobrado.

## Alertas no celular (grátis, opcional)
1. Crie um bot no Telegram com o @BotFather.
2. Copie `.env.example` para `.env`.
3. Cole `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
4. Reinicie.

Não mande o `.env` para ninguém.

## Coisas pagas
Coinglass, Whale Alert e X ficam desligados. Não precisa deles. Se um dia colocar a chave no `.env`, eles ligam sozinhos.
Os preços estão em `docs/PLANO.md`.
