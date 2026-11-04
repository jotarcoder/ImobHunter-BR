# Windows 2.1.1: bloqueio Microsoft Defender em 04/11/2026

O usuário relatou "Não foi possível baixar — Vírus detectado" no Edge para
`ImobHunter-BR-Setup-Windows-2.1.1.exe`. O alerta **não é equivalente** ao
aviso de reputação "editor desconhecido" do SmartScreen; não presumir falso
positivo e não orientar a desativar o antivírus ou criar exceções.

Origem do candidato: workflow Windows de release #41767418671, commit
`b80f70b6a58b7a1769606ad89b8480404e26a800`, quatro builds verdes e
manifesto SHA256. A publicação no R2 ocorreu via #41768283866, mas o pipeline
de release não fez antivírus nem assinatura Authenticode do instalador.

Investigação proposta:
1. Obter em **Segurança do Windows → Proteção contra vírus e ameaças →
   Histórico de proteção** o **nome da ameaça** e o horário da detecção,
   preservando a quarentena. Sem esse dado, não afirmar que é um falso positivo.
2. Executar o workflow de varredura do arquivo **original** no GitHub Actions
   em runner Windows, sem rodar o instalador nem recompilar nada. A checagem
   valida SHA256 e Authenticode. Resultado negativo em um runner não significa
   ausência de ameaça para toda assinatura/versão do Defender.
3. Se a classificação for incorreta após revisão, submeter o **arquivo**
   ao portal Microsoft Security Intelligence pelo canal *Software developer*:
   https://www.microsoft.com/wdsi/filesubmission. O formulário aceita no
   máximo 50 MB; o instalador tem ~126 MB, então deve-se avaliar o arquivo
   detectado específico (quando for um componente extraído), não adulterar
   o binário ou solicitar ao usuário para ignorar o bloqueio.
4. Implantar assinatura Authenticode de editor verificado (aplicativo e
   instalador) como projeto específico após disponibilização de identidade
   verificada/certificado. Assinar **não** corrige malware real nem garante
   sumiço do SmartScreen.
5. Somente alterar instalador Windows/R2 após triagem, correção verificável,
   novo PR e execução de QA + antivírus. Não republicar os quatro pacotes
   desnecessariamente e não apagar evidências da detecção.

Os ajustes de layout dos cartões da landing são independentes do instalador.
