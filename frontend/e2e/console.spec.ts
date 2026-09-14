import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

test('project inventory, original download, TLR and evidence drill-down', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', e => errors.push(e.message));
  const id = `browser-${Date.now()}`;
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '所有项目' })).toBeVisible();
  await page.getByRole('button', { name: '新建项目', exact: true }).first().click();
  await page.getByLabel('项目名称').fill('端到端测试项目（测试模型）');
  await page.getByLabel('项目标识').fill(id);
  await page.getByRole('button', { name: '创建项目', exact: true }).click();
  await page.getByRole('button', { name: '上传资料', exact: true }).click();
  await page.getByLabel('本次资料版本').fill('v1');
  await page.getByLabel('选择本地文件', { exact: true }).setInputFiles([
    { name: 'R1.md', mimeType: 'text/markdown', buffer: Buffer.from('用户应能 login 登录。') },
    { name: 'C1.py', mimeType: 'text/plain', buffer: Buffer.from('def login():\n    return True\n') },
  ]);
  await page.getByLabel('R1.md 的类型').selectOption('requirement');
  await page.getByLabel('C1.py 的类型').selectOption('code');
  await page.getByRole('button', { name: '上传并保存' }).click();
  await page.getByRole('link', { name: /R1.md/ }).click();
  await expect(page.locator('.qm-document')).toContainText('用户应能 login 登录。');
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('link', { name: '下载原始文件' }).click();
  expect((await downloadEvent).suggestedFilename()).toBe('R1.md');
  await page.getByRole('link', { name: '返回项目', exact: true }).click();
  await page.getByRole('button', { name: '重新进行 TLR 检测' }).click();
  await page.getByRole('button', { name: '手工选择源与目标制品', exact: true }).click();
  await page.getByRole('button', { name: '需求 → 代码', exact: true }).click();
  await page.getByRole('button', { name: '开始检测', exact: true }).click();
  await expect(page.locator('h1 .qm-badge')).toHaveText('已完成', { timeout: 30000 });
  await expect(page.locator('.qm-graph canvas').first()).toBeVisible();
  await mkdir('../artifacts/console-qa', { recursive: true });
  await page.screenshot({ path: '../artifacts/console-qa/tlr-desktop.png', fullPage: true });
  await page.getByRole('tab', { name: '追踪矩阵' }).click();
  await page.getByRole('button', { name: 'R1.md → C1.py：最终链接', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('test fixture matching');
  await expect(page.getByRole('dialog')).toContainText('用户应能 login 登录。');
  await page.keyboard.press('Escape');
  await page.getByRole('tab', { name: /候选与判定/ }).click();
  await page.getByRole('button', { name: '查看证据', exact: true }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await page.getByRole('link', { name: '返回项目资料' }).click();
  await page.getByRole('tab', { name: /TLR 运行记录/ }).click();
  await expect(page.getByRole('link', { name: '查看结果' })).toBeVisible();
  await page.getByRole('tab', { name: '资料清单' }).click();
  await page.screenshot({ path: '../artifacts/console-qa/project-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '../artifacts/console-qa/project-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('backend failure is visible without placeholder projects', async ({ page }) => {
  await page.route('**/api/v1/tlr/projects?*', route => route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ msg: '数据库不可用' }) }));
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('数据库不可用');
  await expect(page.locator('.qm-project-card')).toHaveCount(0);
});


test('layer matrix defaults, cross-layer selection and original structure navigation', async ({page,request})=>{
  const project='layers-'+Date.now();
  const payload={tenant_id:'local',project_id:project,version:'layer-test',artifacts:[
    {external_id:'N',kind:'natural_language',content:'login context.',structure:{title:'Background',relations:[{target_id:'R',relation:'dataset_trace'}]}},
    {external_id:'R',kind:'requirement',content:'login shall work.',structure:{title:'Requirement',parent_ids:['N'],relations:[{target_id:'D',relation:'dataset_trace'}]}},
    {external_id:'D',kind:'design',content:'login design.',structure:{title:'Design',parent_ids:['R'],relations:[{target_id:'C',relation:'dataset_trace'}]}},
    {external_id:'C',kind:'code',locator:'login.py',content:'def login():\n    return True\n',structure:{title:'Code',parent_ids:['D'],relations:[{target_id:'T',relation:'dataset_trace'}]}},
    {external_id:'T',kind:'test_case',content:'login test: expect login success.',structure:{title:'Test case',parent_ids:['C']}},
    {external_id:'REF',kind:'code',content:'missing.java',structure:{content_status:'reference_only',title:'Missing source',parent_ids:['D']}},
  ].map(a=>({...a,revision:'v1'}))};
  const response=await request.post('http://127.0.0.1:18080/api/v1/tlr/datasets',{data:payload});expect(response.ok()).toBeTruthy();
  await page.goto('/quality.html#/projects/'+project);
  await page.getByRole('tab',{name:'结构关系',exact:true}).click();
  await page.getByRole('button',{name:'展开 Background',exact:true}).click();
  await page.getByRole('link',{name:'Requirement',exact:true}).click();
  await expect(page.getByRole('heading',{name:'原始结构关系',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'Background',exact:true})).toBeVisible();
  await page.getByRole('link',{name:'返回项目',exact:true}).click();
  await page.getByRole('button',{name:'重新进行 TLR 检测',exact:true}).click();
  await expect(page.locator('dialog input[type=checkbox]:checked')).toHaveCount(4);
  await page.getByRole('checkbox',{name:'需求 → 测试用例 / 测试代码',exact:true}).check();
  await expect(page.locator('dialog input[type=checkbox]:checked')).toHaveCount(5);
  await page.getByText('按制品类型配置分割粒度',{exact:true}).click();
  await page.getByLabel('源代码 分割策略',{exact:true}).selectOption('method');
  await page.screenshot({path:'../artifacts/console-qa/layer-selection.png',fullPage:true});
  await page.getByRole('button',{name:'创建并依次检测',exact:true}).click();
  await expect(page.getByRole('heading',{name:'层间运行矩阵',exact:true})).toBeVisible();
  await expect(page.locator('section.qm-inset .qm-badge.completed')).toHaveCount(5,{timeout:30000});
  await page.screenshot({path:'../artifacts/console-qa/layer-results.png',fullPage:true});
});
