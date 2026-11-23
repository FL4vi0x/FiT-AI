# Honda Fit GD 2005 LX BR — diagnóstico da v3 e estudo de viabilidade (Portão 0)

Nada foi modelado nesta etapa. v1, v2 e v3 estão intactas. Medições: `scripts/diagnose_v3.py` → `out/v3/diagnosis_v3.json`.

## 1. Defeitos medidos na v3 e suas causas

| Defeito visto | Causa técnica (evidência) | É geometria ou renderização? |
|---|---|---|
| Nariz arredondado, sem definição | Cada seção transversal é calculada por **duas silhuetas**: a altura vem do perfil lateral (máximo na largura) e a largura da vista de cima (máximo na altura). O nariz é o produto dessas duas funções, então não há painéis (capô, para-lama, para-choque), nem fendas entre eles. Só 3,35% das arestas passam de 35°. As 128–168 seções se concentram na ponta (13 linhas nos primeiros 5 cm, onde não há detalhe) e a zona capô→para-choque tem pouca resolução. | Geometria |
| Flancos planos | Todas as seções usam a mesma tabela de largura por altura (`wn(h)`, tirada da silhueta frontal) escalada pela largura em planta. A superfície é praticamente uma **varredura**; as variações (flare, soleira, vinco) são deslocamentos aditivos de 16–24 mm. Desvio-padrão das normais no flanco entre eixos: 4,75°. Um flanco real tem curvatura composta. | Geometria |
| Janelas e teto serrilhados | O vidro é uma **casca separada** feita por raios em grade de 7 mm, a 6 mm da pele. A borda é a escada da grade (440 a 850 arestas abertas por casca). No teto, raios altos erram parte do corpo e geram zigue-zague. A carroceria não tem aberturas de janela nem colunas reais. | Geometria (método) |
| Faróis "colados" | Também cascas abertas (316 arestas abertas), a distância uniforme de 14 mm da pele, não soldadas e sem alojamento. A carroceria não tem abertura de farol. Os retrovisores flutuam a 43–156 mm do corpo (sem haste). | Geometria (método) |
| Topologia | 4 arestas non-manifold, 2 de borda e 2 faces de área zero (tampas do nariz e da traseira). **18% das faces com proporção > 8:1** (seções a 3,4 cm entre si contra segmentos de 1–4 cm). Os pneus **atravessam** o corpo (61–63 pares de triângulos cada). | Geometria |
| "V" e manchas | Sombreamento suave sobre a tampa em leque e sobre triângulos esticados. | Geometria + sombreamento |
| Normais | Não estão invertidas no geral (volume com sinal +5,83 m³). 88 faces têm a normal voltada para dentro de concavidades (arcos de roda, friso), o que é esperado. | — |
| Aparência cinza e chapada | Workbench com luz de estúdio e sem reflexo esconde curvatura. Isso afeta a leitura, mas não cria os defeitos acima. | Renderização (secundário) |

Conclusão: **o problema é o método**. Subdividir, chanfrar ou suavizar uma varredura de duas silhuetas só arredonda; não cria painéis nem alojamentos.

## 2. Técnica recomendada

**Rede de curvas características → painéis separados (meia malha + Mirror).**
1. Digitalizar em 3D as linhas do carro a partir de vistas calibradas: linha de cintura, vinco do ombro, soleira, contorno do capô e seu friso, base do para-brisa, colunas A/B/C, trilhos do teto, borda dos arcos de roda, contornos de farol, grade, lanterna, tampa traseira, bordas superior e inferior dos para-choques.
2. Modelar painéis separados entre loops de aresta definidos (capô, para-lamas, para-choques, portas, teto com colunas, laterais traseiras, tampa traseira, soleiras) com fluxo de quads controlado; as aberturas (farol, grade, janelas, arcos) seriam loops reais, com alojamento interno.
3. Subdivision Surface nível 1–2 com pesos de vinco só nas fendas entre painéis; Mirror; normais por ângulo.
4. Verificação por faixas zebra e curvatura, como diagnóstico, não como disfarce.

Tudo isso é programável em `bmesh`, **mas os pontos de controle precisam ser autorados**. Seriam lidos por mim nas imagens, com erro de 1–3 cm, sem a visão interativa de um modelador. Se a solução exigir ajuste de vértices no Blender, isso é manual e eu **não o faço**: só refino por script, renderização e comparação.

## 3. Referências
- **Disponíveis:** prancha ortográfica (lateral, frente, traseira, topo); lateral limpa quase ortográfica (cruzei com a prancha: IoU 0,937); frente reta e traseira reta; três 3/4 (dois frontais, um traseiro).
- **Insuficientes ou arriscadas:**
  - A frente da prancha mostra faróis redondos, enquanto as fotos mostram faróis varridos. **Há possível diferença de fase do modelo** (pré e pós-facelift). É preciso confirmar qual frente tem o LX brasileiro 2005.
  - Nenhuma foto ortográfica da frente ou da traseira.
  - Sem detalhes das colunas, da soleira e dos arcos de roda, nem foto de baixo ângulo.

## 4. Opções

| Opção | Fidelidade provável | Esforço | Riscos |
|---|---|---|---|
| A. Procedural (painéis por script) | Reconhecível na dianteira com chance moderada; carro inteiro: média | Alto, muitas iterações | Pode continuar genérico; conexões G1 entre painéis difíceis de garantir; erro de leitura de 1–3 cm |
| B. Modelo existente licenciado | A maior | Baixo para mim (escala, nomes, holograma) | Os achados da busca são pagos (3DCadBrowser, TurboSquid, CGTrader, 3DExport); a licença precisa permitir uso (e o repositório é público); a geração GD 2005 precisa ser confirmada |
| C. Fotogrametria do seu próprio carro | Boa nos volumes, pior nos vincos | Médio (você fotografa, o processamento é local) | Brilho do verniz e vidros atrapalham; precisa de 80–150 fotos; limpeza pesada; placa deve ser mascarada |
| D. Modelador humano | Profissional | Custo externo | Prazo e custo |
| E. IA imagem→3D | Baixa para um carro específico | Baixo | Exige enviar fotos a serviço externo ou baixar modelos, ambos vetados; malha instável |
| F. Híbrido | Alta | Médio | Parte manual |

## 5. Eu consigo, só com Blender Python, sem modelagem manual?
Não posso garantir. Acredito ser possível chegar a uma **dianteira reconhecível** com a técnica da seção 2. Uma carroceria **profissional e fiel** do carro inteiro, só com Python e referências 2D, é improvável: a fidelidade depende da curvatura fina que um modelador ajusta olhando o modelo, e o meu ciclo de renderizar e comparar é mais lento e mais grosseiro.

## 6. Proposta
1. **Protótipo isolado da dianteira**, não do carro: capô, transição para os para-lamas, aberturas de farol, face frontal e transição para o para-choque, em cinza uniforme.
2. Critério de parada: se continuar genérico, **interrompo a modelagem procedural** e recomendo B, C ou D.
3. Em paralelo, e sem custo para mim, vale decidir qual fase do Fit (pré ou pós-facelift) é o seu carro e verificar uma opção B.
