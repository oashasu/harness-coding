import Database from 'better-sqlite3';
import * as fs from 'fs';
import * as path from 'path';

interface ExtractedRule {
  rule_content: string;
  domain_id: string;
  rule_type: 'constraint' | 'pattern' | 'pitfall' | 'convention';
  confidence: number;
  source_type: string;
  source_file: string;
}

/**
 * 从SDD文档中提取编码规范和业务规则
 */
export function importSddDocuments(db: Database.Database, sddDir: string): number {
  let imported = 0;

  // 1. 导入代码规范
  const codeConventionsFile = path.join(sddDir, '01_代码规范提取.md');
  if (fs.existsSync(codeConventionsFile)) {
    imported += importCodeConventions(db, codeConventionsFile);
  }

  // 2. 导入业务规范
  const businessRulesFile = path.join(sddDir, '02_业务规范提取.md');
  if (fs.existsSync(businessRulesFile)) {
    imported += importBusinessRules(db, businessRulesFile);
  }

  // 3. 导入红队发现（作为pitfall）
  const redTeamFile = path.join(sddDir, '04_红队验收.md');
  if (fs.existsSync(redTeamFile)) {
    imported += importRedTeamFindings(db, redTeamFile);
  }

  // 4. 导入前端规范
  const frontendFile = path.join(sddDir, '06_前端代码规范提取.md');
  if (fs.existsSync(frontendFile)) {
    imported += importFrontendConventions(db, frontendFile);
  }

  return imported;
}

function importCodeConventions(db: Database.Database, filePath: string): number {
  const content = fs.readFileSync(filePath, 'utf-8');
  const rules: ExtractedRule[] = [];

  // 提取汇总表中的规范
  const summaryMatch = content.match(/\| 编号 \| 规范项 \| 核心规则 \| 可信度 \|[\s\S]*?(?=\n##|$)/);
  if (summaryMatch) {
    const rows = summaryMatch[0].split('\n').filter(line => line.startsWith('|') && !line.includes('编号'));
    for (const row of rows) {
      const cols = row.split('|').map(c => c.trim()).filter(Boolean);
      if (cols.length >= 3) {
        rules.push({
          rule_content: `${cols[1]}: ${cols[2]}`,
          domain_id: 'hjly-admin-console',
          rule_type: 'convention',
          confidence: cols[3]?.includes('高') ? 0.95 : 0.8,
          source_type: 'sdd_extraction',
          source_file: filePath
        });
      }
    }
  }

  // 提取分层结构
  const layerMatch = content.match(/## 1\. 分层结构与模块职责[\s\S]*?(?=\n## 2|$)/);
  if (layerMatch) {
    rules.push({
      rule_content: '分层架构: common → dal → service → web; dependency 独立与 dal 平行',
      domain_id: 'hjly-admin-console',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 提取注入规范
  if (content.includes('@Resource') && content.includes('禁止 @Autowired')) {
    rules.push({
      rule_content: '依赖注入: 全项目统一使用 @Resource，禁止 @Autowired，字段注入模式',
      domain_id: 'hjly-admin-console',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 提取返回值规范
  if (content.includes('AjaxModel')) {
    rules.push({
      rule_content: 'Controller返回值: JSON用 AjaxModel.success()/error()，页面用 ModelAndView',
      domain_id: 'hjly-admin-console',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 提取异常体系
  if (content.includes('DalException') && content.includes('ServiceException')) {
    rules.push({
      rule_content: '异常体系: 四层异常(Dal/Service/Dependency/App) + 错误码(DAL_xx_xx_xxx, S_xx_xx_xxx, D_xx_xx_xxx)',
      domain_id: 'hjly-admin-console',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 提取日志规范
  if (content.includes('ErrorLogger') && content.includes('SystemLogger')) {
    rules.push({
      rule_content: '日志规范: ErrorLogger仅用于带堆栈异常(catch块)，SystemLogger用于info/warn，禁止System.out',
      domain_id: 'hjly-admin-console',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 提取DTO转换规范
  if (content.includes('transform()') && content.includes('ListUtils')) {
    rules.push({
      rule_content: 'DTO转换: 使用静态 transform() 方法 + ListUtils.transform(list, XxxDTO::transform)',
      domain_id: 'hjly-admin-console',
      rule_type: 'pattern',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 提取测试规范
  if (content.includes('SpringBaseTest') && content.includes('AssertJ')) {
    rules.push({
      rule_content: '测试规范: 集成测试继承SpringBaseTest，Mock测试继承AbstractMockTest，断言用AssertJ禁止JUnit原生',
      domain_id: 'hjly-admin-console',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  return insertRules(db, rules);
}

function importBusinessRules(db: Database.Database, filePath: string): number {
  const content = fs.readFileSync(filePath, 'utf-8');
  const rules: ExtractedRule[] = [];

  // 提取服务域清单
  const domainSection = content.match(/## 1\. 服务域清单[\s\S]*?(?=\n## 2|$)/);
  if (domainSection) {
    const domainRows = domainSection[0].split('\n').filter(line => line.startsWith('|') && !line.includes('域名称'));
    for (const row of domainRows) {
      const cols = row.split('|').map(c => c.trim()).filter(Boolean);
      if (cols.length >= 2) {
        rules.push({
          rule_content: `业务域: ${cols[0]} - ${cols[2] || cols[1]}`,
          domain_id: cols[1]?.replace(/[()]/g, '') || 'unknown',
          rule_type: 'convention',
          confidence: 0.9,
          source_type: 'sdd_extraction',
          source_file: filePath
        });
      }
    }
  }

  // 提取核心业务规则（密码规则等）
  const passwordRules = [
    '密码规则：8位以上大小写字母+数字',
    '密码规则：6位以上字母或数字',
    '密码规则：大小写+数字+特殊字符'
  ];
  for (const rule of passwordRules) {
    if (content.includes(rule)) {
      rules.push({
        rule_content: rule,
        domain_id: 'platform',
        rule_type: 'constraint',
        confidence: 0.9,
        source_type: 'sdd_extraction',
        source_file: filePath
      });
    }
  }

  // 提取TODO中的硬编码问题
  const hardcodedIssues = [
    '预付款支付是否验证密码暂时写死',
    '在线充值支付有效期写死2小时',
    '预付款支付是否需要输密码暂时写死'
  ];
  for (const issue of hardcodedIssues) {
    if (content.includes(issue)) {
      rules.push({
        rule_content: `硬编码风险: ${issue}`,
        domain_id: 'pay',
        rule_type: 'pitfall',
        confidence: 0.85,
        source_type: 'sdd_extraction',
        source_file: filePath
      });
    }
  }

  return insertRules(db, rules);
}

function importRedTeamFindings(db: Database.Database, filePath: string): number {
  const content = fs.readFileSync(filePath, 'utf-8');
  const rules: ExtractedRule[] = [];

  // SQL注入风险
  if (content.includes('${query.sort}') || content.includes('${query.order}')) {
    rules.push({
      rule_content: '安全红线: 禁止 ${} 拼接 ORDER BY，必须使用白名单字段校验（material-detail-read-mapper.xml:116,157, site-protocol-config-read-mapper.xml:408）',
      domain_id: 'hjly-admin-console',
      rule_type: 'constraint',
      confidence: 0.99,
      source_type: 'red_team_audit',
      source_file: filePath
    });
  }

  // XSS风险
  if (content.includes('th:utext')) {
    rules.push({
      rule_content: '安全红线: 禁止 th:utext，必须使用 th:text（自动转义），确需富文本时使用OWASP HtmlSanitizer净化',
      domain_id: 'hjly-admin-console',
      rule_type: 'constraint',
      confidence: 0.99,
      source_type: 'red_team_audit',
      source_file: filePath
    });
  }

  // @Transactional rollbackFor
  if (content.includes('740') && content.includes('rollbackFor')) {
    rules.push({
      rule_content: '事务规范: 所有 @Transactional 必须指定 rollbackFor = Exception.class（项目存在740处缺失）',
      domain_id: 'hjly-admin-console',
      rule_type: 'constraint',
      confidence: 0.95,
      source_type: 'red_team_audit',
      source_file: filePath
    });
  }

  // 异常信息泄露
  if (content.includes('GlobalExceptionHandler') && content.includes('信息泄露')) {
    rules.push({
      rule_content: '安全规范: GlobalExceptionHandler禁止直接返回e.getMessage()给客户端，需映射为通用错误消息',
      domain_id: 'hjly-admin-console',
      rule_type: 'constraint',
      confidence: 0.95,
      source_type: 'red_team_audit',
      source_file: filePath
    });
  }

  // 拼写错误
  if (content.includes('recieve')) {
    rules.push({
      rule_content: '命名规范: "receive"正确拼写，项目存在16处"recieve"拼写错误（含DB列名），新代码禁止使用',
      domain_id: 'hjly-admin-console',
      rule_type: 'pitfall',
      confidence: 0.9,
      source_type: 'red_team_audit',
      source_file: filePath
    });
  }

  return insertRules(db, rules);
}

function importFrontendConventions(db: Database.Database, filePath: string): number {
  const content = fs.readFileSync(filePath, 'utf-8');
  const rules: ExtractedRule[] = [];

  // 技术栈
  const techStack = [
    { name: '模板引擎', value: 'Thymeleaf' },
    { name: 'CSS框架', value: 'Bootstrap 4.3.1' },
    { name: 'JS基础', value: 'jQuery 3.5.0' },
    { name: '表格组件', value: 'bootstrap-table + hjly-table.js封装' },
    { name: 'AJAX封装', value: 'abp.ajax() 统一请求封装' },
    { name: '表单验证', value: 'jQuery Validate + hjly自定义规则' },
    { name: '国际化', value: 'jquery.i18n.properties' }
  ];

  for (const tech of techStack) {
    if (content.includes(tech.value)) {
      rules.push({
        rule_content: `前端技术栈: ${tech.name} = ${tech.value}`,
        domain_id: 'hjly-admin-console-frontend',
        rule_type: 'convention',
        confidence: 0.95,
        source_type: 'sdd_extraction',
        source_file: filePath
      });
    }
  }

  // 页面模式
  if (content.includes('hjlyBootstrapTable')) {
    rules.push({
      rule_content: '前端列表页模式: 使用 hjlyBootstrapTable 封装，包含 queryForm + tabList + reloadTable()',
      domain_id: 'hjly-admin-console-frontend',
      rule_type: 'pattern',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  if (content.includes('formEdit')) {
    rules.push({
      rule_content: '前端表单页模式: 使用 formEdit 表单，col-sm-3 col-md-2 label + col-sm-9 col-md-4 input 布局',
      domain_id: 'hjly-admin-console-frontend',
      rule_type: 'pattern',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // 组件引入规范
  if (content.includes('hjly-include')) {
    rules.push({
      rule_content: '前端组件引入: 使用 <hjly-include th:replace="..."> 引入 layout/ 片段（自定义标签）',
      domain_id: 'hjly-admin-console-frontend',
      rule_type: 'convention',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  // AJAX模式
  if (content.includes('abp.ajax')) {
    rules.push({
      rule_content: '前端AJAX模式: abp.ajax({url, data, type}) → done(json => { if(json.success) reloadTable() })',
      domain_id: 'hjly-admin-console-frontend',
      rule_type: 'pattern',
      confidence: 0.95,
      source_type: 'sdd_extraction',
      source_file: filePath
    });
  }

  return insertRules(db, rules);
}

function insertRules(db: Database.Database, rules: ExtractedRule[]): number {
  const stmt = db.prepare(`
    INSERT INTO business_rules (rule_content, domain_id, rule_type, confidence, source_type, source_file, created_at)
    VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
  `);

  let inserted = 0;
  for (const rule of rules) {
    try {
      stmt.run(rule.rule_content, rule.domain_id, rule.rule_type, rule.confidence, rule.source_type, rule.source_file);
      inserted++;
    } catch (e) {
      // 忽略重复
    }
  }

  return inserted;
}
