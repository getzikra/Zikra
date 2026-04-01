-- zikra-statusline.lua
-- Drop this file into ~/.config/nvim/lua/ and require it from init.lua:
--   require('zikra-statusline')
--
-- Or paste the contents directly into your init.lua / init.vim (wrapped in lua << EOF ... EOF)

-- ── Highlight groups ──────────────────────────────────────────────────────────
-- Z        = full Zikra orange, bold
-- ikra     = dimmed Zikra orange (~55% brightness), regular weight
-- Bracket  = very subtle separator tint (optional, remove if you prefer plain │)

vim.api.nvim_set_hl(0, 'ZikraZ',       { fg = '#E8730A', bold = true,  italic = false })
vim.api.nvim_set_hl(0, 'ZikraRest',    { fg = '#7A3A0A', bold = false, italic = false })
vim.api.nvim_set_hl(0, 'ZikraSep',     { fg = '#3D2005', bold = false })  -- subtle separator

-- Re-apply highlights after colorscheme changes so the wordmark survives :colorscheme switches
vim.api.nvim_create_autocmd('ColorScheme', {
  pattern = '*',
  callback = function()
    vim.api.nvim_set_hl(0, 'ZikraZ',    { fg = '#E8730A', bold = true  })
    vim.api.nvim_set_hl(0, 'ZikraRest', { fg = '#7A3A0A', bold = false })
    vim.api.nvim_set_hl(0, 'ZikraSep',  { fg = '#3D2005', bold = false })
  end,
})

-- ── Plain statusline (no lualine) ─────────────────────────────────────────────
-- Uses Neovim's built-in %#GroupName# syntax.
-- The wordmark sits at the far left, then standard file info follows.
--
-- Layout:  Zikra │ filename [modified] │ filetype       line:col  %

local function set_plain_statusline()
  vim.opt.statusline = table.concat({
    '%#ZikraZ#Z',            -- bright orange Z
    '%#ZikraRest#ikra',      -- dimmed orange ikra
    '%#ZikraSep# │ ',        -- subtle separator
    '%#StatusLine#',         -- reset to theme default
    '%f',                    -- relative file path
    ' %m',                   -- [+] if modified, [-] if nomodifiable
    '%=',                    -- push everything after this to the right
    '%y ',                   -- [filetype]
    '%l:%c ',                -- line:col
    '%P',                    -- percentage through file
  })
end

-- ── lualine component (if lualine is present) ─────────────────────────────────
-- Returns a lualine component table ready to drop into sections.lualine_a or _b.
--
-- Usage in your lualine setup:
--
--   local zikra = require('zikra-statusline').lualine_component()
--
--   require('lualine').setup({
--     sections = {
--       lualine_a = { zikra, 'mode' },   -- wordmark before mode
--       -- or:
--       lualine_b = { zikra, 'branch' }, -- wordmark before branch
--     }
--   })

local function lualine_component()
  return {
    -- lualine renders the string as-is and applies the color returned by color()
    -- We return the raw highlight sequence directly so both glyphs get individual colors.
    function()
      -- lualine strips highlight codes from the string value, so we use
      -- the component's `fmt` trick: return a plain string and apply color via
      -- the separator + padding approach, relying on the color() function below.
      -- For true two-tone, we return the full highlight-escaped string and set
      -- color to 'none' so lualine doesn't override it.
      return '%#ZikraZ#Z%#ZikraRest#ikra'
    end,
    color = 'Normal',      -- prevent lualine from wrapping in its own highlight
    padding = { left = 1, right = 1 },
    separator = { left = '', right = '│' },
  }
end

-- ── Auto-detect and apply ─────────────────────────────────────────────────────
-- If lualine is loaded, patch it. Otherwise set the plain statusline.
-- Call M.setup() from your init.lua, or just require() this file directly.

local M = {}

M.lualine_component = lualine_component

function M.setup(opts)
  opts = opts or {}

  local has_lualine, lualine = pcall(require, 'lualine')

  if has_lualine and not opts.force_plain then
    -- Patch lualine: prepend the Zikra wordmark to lualine_a (or lualine_b if specified)
    local section = opts.section or 'lualine_a'
    local cfg = lualine.get_config and lualine.get_config() or {}
    cfg.sections = cfg.sections or {}
    cfg.sections[section] = cfg.sections[section] or {}
    -- Prepend, not append, so it's always leftmost
    table.insert(cfg.sections[section], 1, lualine_component())
    lualine.setup(cfg)
  else
    -- Fallback: plain built-in statusline
    set_plain_statusline()
  end
end

-- Auto-run setup on require (safe default)
M.setup()

return M
