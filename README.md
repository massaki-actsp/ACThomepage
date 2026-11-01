# ACT-SP Homepage

Projeto Flask/WSGI para servir a homepage da ACT-SP e receber mensagens do formulário de contato.

## Publicacao no PythonAnywhere

O guia completo está em [docs/DEPLOY_PYTHONANYWHERE.md](docs/DEPLOY_PYTHONANYWHERE.md):
autenticação GitHub no PowerShell, envio do projeto, PostgreSQL do Supabase,
configuração WSGI, arquivos estáticos, CNAME no Registro.br e HTTPS.
Essa configuração requer plano pago do PythonAnywhere para domínio próprio e
acesso ao PostgreSQL externo. As integrações externas ainda não foram executadas.

Os assets agora usam `/static/`, gerados com `url_for('static', ...)`. No painel
Web, mapeie `/static/` para `/home/SEU_USUARIO/ACThomepage/static`.
As URLs antigas `/css/`, `/images/` e `/js/` não são mais usadas. APIs e páginas
continuam nas mesmas rotas. O Render continua usando `gunicorn wsgi:app`;
no PythonAnywhere use `application` e o WSGI gerenciado pela plataforma.

## Arquitetura

O Flask entrega as páginas HTML e os assets estáticos. O arquivo `static/js/contact.js` envia o formulário para `POST /api/contact` usando JSON. A API valida os campos no servidor e grava a mensagem na tabela `contact_messages`. Em produção, a variável `DATABASE_URL` aponta para o PostgreSQL do Supabase.

Este pacote implementa login administrativo local para consulta e organização das mensagens recebidas. Ele não implementa envio de e-mail. A integração atual termina na gravação segura da mensagem no banco.

## Execução local

```powershell
python -m venv ACThomepage
.\\ACThomepage\\Scripts\\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
$env:CREATE_TABLES = "true"
$env:DATABASE_URL = "sqlite:///instance/actsp.db"
python app.py
```

Acesse `http://127.0.0.1:5000`.

## Testes

```powershell
pytest
```

Os testes usam um banco SQLite temporário para validar rotas, rejeição de dados inválidos e gravação de uma mensagem. Para produção, use Supabase/PostgreSQL.

## Modulo Mural

Salve os arquivos `.mp4` em `static/videos/`. A pagina `/mural.html` carrega o catalogo de `data/mural.csv` e exibe uma interface no estilo streaming: destaque principal, metadados, carrossel, catalogo filtravel e player local ou incorporado.

Para personalizar o catalogo, edite `data/mural.csv`. Campos principais:

```csv
id;title;description;category;year;duration;rating;poster;banner;video;provider;embed_url;caption;featured
1;SindCON ERP;Demonstracao do SindCON ERP.;Sistema ERP;2026;Demonstracao;Livre;SindCON_ERP_App.png;banner1.jpg;;youtube;https://youtu.be/SD5lW53LIE4;;sim
```

### Videos locais, YouTube e Vimeo

O botão **Assistir agora** aceita MP4 local, links do YouTube e links do Vimeo,
configurados em `data/mural.csv`. Não é necessário baixar os vídeos externos.
O arquivo `data/mural-exemplo.csv` contém uma linha de cada tipo para referência;
ele não substitui automaticamente o catálogo atual nem seus IDs.
Use as colunas abaixo e mantenha título, descrição, categoria e capa preenchidos:

| Tipo | `provider` | `video` | `embed_url` |
| --- | --- | --- | --- |
| MP4 local | `local` | `SindCON_ERP.mp4` | vazio |
| YouTube | `youtube` | vazio | `https://youtu.be/Mi7CkzLP38c` |
| Vimeo | `vimeo` | vazio | `https://vimeo.com/76979871` |

Também é aceito `provider=embed`: o serviço é identificado pelo link. Para
facilitar a edição de linhas locais, colar uma URL válida na coluna `video`
também identifica o serviço automaticamente quando `embed_url` estiver vazio.
Prefira as colunas explícitas da tabela para manter o catálogo organizado.

O servidor transforma os links em URLs HTTPS dos players oficiais. YouTube
aceita links `watch?v=`, `youtu.be`, `shorts`, `live` e `/embed/`. Vimeo aceita
`vimeo.com/ID`, `player.vimeo.com/video/ID` e links não listados com hash
(`vimeo.com/ID/HASH` ou `?h=HASH`). O hash é preservado ao iniciar a reprodução.
Outros domínios, protocolos perigosos e combinações de provider/link incompatíveis
são rejeitados. Não cole código `<iframe>` inteiro: utilize somente a URL.

O vídeo deve permitir incorporação nas configurações do YouTube/Vimeo. Restrições
de domínio, privacidade ou autenticação impostas pelo provedor continuam valendo.
Os players externos só são carregados ao clicar em **Assistir agora**; o destaque
de vídeos externos usa as imagens locais. Os logs de cliques funcionam para os
três tipos. Mantenha IDs estáveis no CSV.

A coluna opcional `open_on_select` com valor `sim` abre o player diretamente ao
clicar no card. Em branco, o card seleciona o conteúdo para o botão **Assistir
agora**. O item **App Check List Digital** usa abertura direta e o vídeo
`https://youtu.be/xNwLNd8POC4`, mantendo o ID `5`.

### Rotas do Mural

- `/mural`
- `/mural.html`
- `/api/mural`
- `/media/mural/<arquivo.mp4>`

Se os arquivos do mural estiverem em outra pasta do drive, configure no `.env`:

```powershell
$env:MURAL_LIBRARY_PATH = "C:\\caminho\\para\\videos"
$env:MURAL_DATA_PATH = "data/mural.csv"
```

## Admin

O painel administrativo fica em `/admin`. Sem login, a rota redireciona para `/admin/login`.

Para baixar todas as mensagens salvas, escolha XLSX ou CSV em **Exportar todas**
e clique em **Download**. A exportação inclui ID, nome, telefone, e-mail, mensagem,
status, prioridade e datas de recebimento e atualização, independentemente dos
filtros do Kanban. O CSV usa UTF-8 com BOM e separador ponto e vírgula; o XLSX
preserva telefones como texto. Com a base vazia, o arquivo contém os cabeçalhos.
Os arquivos são gerados em memória pela rota autenticada
`GET /admin/messages/export?format=xlsx` (ou `format=csv`).
Após atualizar o projeto, execute `pip install -r requirements.txt` para instalar
a dependência de exportação XLSX.

Configure as credenciais no `.env`:

```powershell
$env:ADMIN_USERNAME = "admin"
$env:ADMIN_PASSWORD = "sua-senha-forte"
```

## Agenda administrativa

No Admin, use a aba **Agenda** ou o botão **Agendar** de uma mensagem.
O calendário mensal permite navegar entre meses, criar, editar e excluir
compromissos. No formulário, **Importar mensagens** permite selecionar até dez
mensagens e copiar seus dados para o compromisso. Nome, e-mail, telefone e texto
ficam preservados como histórico, mesmo que o contato original seja excluído.
As mensagens originais e seus status não são alterados pelo agendamento.

Informe título, tipo, início, término, local e descrição. Os horários usam
`America/Sao_Paulo`; sem término, a duração é de uma hora. Após salvar, o botão
**Google Agenda** abre o Google com título, datas, local, descrição e contatos
preenchidos. Confirme o salvamento no Google. O link não sincroniza alterações,
não envia convites automaticamente e não exige chave de API ou OAuth.

Ao importar mensagens, o formulário sugere o próximo horário de meia hora para
o início, que pode ser alterado antes de salvar. Campos obrigatórios ou datas
inválidas mostram um aviso na página. Após salvar, a agenda abre no mês do evento
e posiciona a tela no compromisso gravado.

Instale as dependências com `python -m pip install -r requirements.txt` e reinicie
a aplicação. No SQLite local, a tabela `agenda_events` é criada automaticamente
sem remover mensagens existentes. No Supabase, execute o `schema.sql` atualizado
antes de usar a Agenda (ou configure `CREATE_TABLES=true` para inicialização).
Com `CREATE_TABLES=false`, o projeto não executa DDL no PostgreSQL.

Rotas protegidas: `/admin/agenda/`, `/admin/agenda/new`,
`/admin/agenda/<id>/edit`, `/admin/agenda/<id>/delete` e
`/admin/agenda/<id>/google`. Formulários da Agenda usam token CSRF.
Adaptação de `Agenda_Module_Export.zip`: calendário, tipos de evento e link Google
foram incorporados ao padrão de persistência SQLite/psycopg do projeto, sem
adicionar uma segunda camada ORM. O vínculo por condomínio do exemplo não é usado.

## LOGs de usuarios do Mural

### Resetar logs e alterar senha

Em **Admin → LOGs de usuários**, expanda **Resetar histórico de cliques**,
informe a senha atual e digite `APAGAR LOGS`. O botão **Apagar todos os logs**
exclui permanentemente os registros de cliques de todos os períodos e zera os
gráficos. Mensagens, compromissos, catálogo e arquivos de vídeo são preservados.
Esta ação não apaga arquivos de log do Flask/Gunicorn ou do provedor de hospedagem.
Faça uma exportação antes se precisar manter uma cópia.

Em **Admin → Segurança**, informe a senha atual, a nova senha (12 a 128
caracteres) e sua confirmação. A nova senha é armazenada como hash em
`admin_credentials`; não é gravada em texto puro nem no `.env`. Após a troca,
todas as sessões administrativas anteriores são invalidadas e um novo login
é necessário. A senha permanece válida após reiniciar a aplicação e é
compartilhada pelos workers que usam o mesmo banco.

As variáveis `ADMIN_PASSWORD`/`ADMIN_PASSWORD_HASH` são usadas enquanto não
houver senha cadastrada no banco para `ADMIN_USERNAME`. Após a primeira troca,
o hash salvo no banco tem precedência; mudar apenas o `.env` não redefine essa
senha. Mantenha `ADMIN_USERNAME` estável entre deploys. No Supabase, execute o
`schema.sql` atualizado antes de iniciar a aplicação. No SQLite local, a tabela
é criada automaticamente. Os dois formulários são protegidos por token CSRF,
autenticação e verificação da senha atual.

Em **Histórico de cliques**, selecione **XLSX** ou **CSV** e clique em **Download**.
O arquivo contém ID do registro, data/hora de Brasília, ID e título do vídeo,
origem e IP. O download respeita o período aplicado e inclui todas as páginas,
inclusive registros de vídeos removidos do catálogo. Sem filtro, exporta todo
o histórico. A rota `/admin/logs/export?format=xlsx` (ou `format=csv`) exige login
administrativo. Datas inválidas são rejeitadas. CSV usa UTF-8 com BOM e ponto e
vírgula; XLSX mantém IPs e textos como texto, com proteção contra fórmulas.

A aba **LOGs de usuários** do Admin (`/admin/logs`) mostra cards de preferência,
gráficos de pizza por vídeo e por origem do clique, e histórico paginado com IP,
vídeo, data e hora. O filtro por período considera dias completos no horário de
Brasília. Datas são gravadas em UTC no servidor e exibidas em `America/Sao_Paulo`.

Cada clique em um card do carrossel, card do catálogo ou botão **Assistir agora**
envia um evento para `POST /api/mural/clicks`. Selecionar um card e depois clicar
em Assistir são duas ações e contam como dois cliques. Autoplay, abertura da
página e restauração da última seleção não geram eventos. Clique não comprova
reprodução nem conclusão do vídeo. Não há identificação de pessoa: IPs podem ser
compartilhados ou mudar. O gráfico apresenta todos os vídeos do catálogo atual,
inclusive os com zero cliques; o percentual é cliques do vídeo / cliques em todos
os vídeos do catálogo atual no período. Vídeos removidos permanecem no histórico
mas não entram no denominador do gráfico. Mantenha os IDs do CSV estáveis e não
reutilize IDs antigos para outro conteúdo.

O servidor valida o ID pelo catálogo, captura o IP da conexão e define o horário,
ignorando IP/título/data enviados no JSON. IDs únicos evitam gravar duas vezes o
mesmo evento. Há limite de 120 eventos por IP por minuto e bloqueio de requisições
de outros sites. Esses controles reduzem abuso; logs de navegador não constituem
auditoria inviolável. Falhas de coleta não interrompem a reprodução.

No SQLite a tabela é criada automaticamente. No Supabase execute `schema.sql`
atualizado antes do deploy. Os gráficos são renderizados localmente em SVG,
sem CDN ou serviço externo de analytics. O histórico é restrito ao administrador
e não é exposto na API pública do Mural. Ajuste sua política de privacidade e
seus procedimentos de retenção ao uso desses registros; os logs não expiram
automaticamente nesta versão.

Os gráficos de pizza mostram percentual (uma casa decimal) e quantidade de
cliques diretamente em cada fatia. Fatias pequenas usam rótulos externos com
linhas de ligação; as legendas mantêm os valores de todos os conteúdos,
incluindo os com zero cliques. O visual segue o exemplo de `autopct` fornecido,
sem exigir Matplotlib ou NumPy no ambiente do servidor.

Para capturar IPs atrás de proxy, configure `TRUSTED_PROXY_COUNT` para a quantidade
real de proxies confiáveis (por exemplo, `1` quando houver um único proxy de
entrada). No acesso direto/local mantenha `0`, ignorando `X-Forwarded-For` que
qualquer cliente pode falsificar. Em produção, o backend deve receber conexões
apenas pela cadeia de proxies configurada. O valor incorreto pode registrar IPs
falsos ou o endereço do proxy. Esta configuração não foi testada no Render.

## Configuracao do Supabase

1. Crie um projeto no Supabase.
2. Abra o SQL Editor e execute `schema.sql`.
3. Copie a connection string PostgreSQL com `sslmode=require`.
4. No Render, configure `DATABASE_URL` com essa string.

Não exponha a senha do banco no front-end. A chave fica somente em variáveis de ambiente do backend.

## Deploy no Render

1. Suba este projeto para um repositório Git.
2. No Render, crie um Web Service a partir do repositório ou use o `render.yaml`.
3. Configure `DATABASE_URL` como variável secreta.
4. Build command: `pip install -r requirements.txt`.
5. Start command: `gunicorn wsgi:app`.

Gunicorn serve a aplicação WSGI no Render. Nginx só é necessário se futuramente você optar por uma VPS.
