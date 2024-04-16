import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class MrpBom(models.Model):
    _name = "mrp.bom"
    _inherit = ['mrp.bom', 'mail.activity.mixin']

    is_bom_template = fields.Boolean('Is Template', default=False)

    bom_template_line_ids = fields.One2many('mrp.bom.template.line', 'bom_id', 'BoM Template Lines', copy=True)

    allowed_product_attribute_ids = fields.One2many('product.attribute', compute='_compute_allowed_product_attribute_ids', string='Allowed PRoduct ATtribute Ids')

    bom_template_id = fields.Many2one('mrp.bom', string='Bom Template', readonly=True)

    related_bom_ids = fields.One2many('mrp.bom', 'bom_template_id', string='Related Bom')

    related_bom_count = fields.Integer(compute='_compute_related_bom_count', string='Related BoM Count')
    
    @api.depends('related_bom_ids')
    def _compute_related_bom_count(self):
        for bom in self:
            bom.related_bom_count = len(bom.related_bom_ids)

    
    @api.depends('product_tmpl_id', 'product_tmpl_id.valid_product_template_attribute_line_ids')
    def _compute_allowed_product_attribute_ids(self):
        for bom in self:
            bom.allowed_product_attribute_ids = bom.product_tmpl_id.valid_product_template_attribute_line_ids.attribute_id

    @api.depends('product_tmpl_id', 'product_id', 'is_bom_template')
    def _compute_display_name(self):
        for bom in self:
            # name = ('[BoM Template] for' if bom.is_bom_template else '[BoM] for') + (bom.product_id.display_name if bom.product_id else product_templ_id.display_name)
            prefix = '[BoM Template] ' if bom.is_bom_template else '[BoM] '
            product_name = bom.product_tmpl_id.display_name
            if bom.product_id:
                product_name = bom.product_id.display_name
            name = prefix + product_name
            bom.display_name = name


    def write(self, vals):
        res = super().write(vals)
        if 'is_bom_template' in vals:
            if vals['is_bom_template']:
                self.active = False
                self.bom_template_id = None
                self.code = 'TEMPLATE'

        if 'product_id' in vals: 
            if not vals['product_id'] and self.bom_template_id:
                self.bom_template_id = False
                self.code = "generated - obsolete"
                self.active = False
        return res

    def action_related_bom(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("mrp.mrp_bom_form_action")
        action['domain'] = [('bom_template_id', '=', self.id)]
        return action        

    def _generate_template_boms(self):
        for bom in self:
            if not bom.is_bom_template:
                _logger.info("BoM %s with id %s is not a template ... skipping", bom, bom.id)
            else:
                tmpl = bom.product_tmpl_id
                result = []
                for variant in tmpl.product_variant_ids:
                    boms = variant.variant_bom_ids
                    template_boms = boms
                    message = []
                    if boms:
                        template_boms = boms.filtered(lambda r: r.bom_template_id == bom)
                    if len(template_boms) > 1:
                        _logger.error("More than 1 templated bom found ...")
                        message.append("Found multiple Templated BoM for variant %s" % variant.display_name)
                    else: 
                        update = False
                        if len(template_boms) == 1:
                            update = True
                            _logger.info("Templated BoM already exists ... re-creating")
                            template_boms.unlink()
                        else :
                            _logger.info("No templated BoM found ... creating")

                        variant_bom_vals = {
                            'is_bom_template' : False,
                            'active' : True,                            
                            'bom_template_line_ids' : [],
                            'bom_template_id' : bom.id,
                            'product_id' : variant.id,
                            'code': 'generated',
                        }

                        variant_bom = bom.copy(variant_bom_vals)

                        bom_msg = _("This BoM has been created from BoM Template")
                        # variant_bom.message_post(body=bom_msg)
                        variant_bom.message_post_with_view(
                            'mail.message_origin_link',
                            values={'self': variant_bom, 'origin': bom},
                            subtype_id=self.env.ref('mail.mt_note').id)                  
                        
                        issues = []

                        for line in bom.bom_template_line_ids:
                            prod = line._generate_bom_line(variant)
                            if not prod:
                                _logger.warning("No matching product found!")
                                issues.append(line.template_id)
                                
                            else:
                                _logger.info("Creating BoM Line")

                                line_vals = {
                                    'product_id': prod.id,
                                    'product_qty': line.product_qty,
                                    'product_uom_id': line.product_uom_id.id,
                                    'sequence': line.sequence,
                                    'bom_id': variant_bom.id,                                    
                                }

                                bom_line = self.env['mrp.bom.line'].create(line_vals)

                        # if issues:
                            # variant_bom.message_post(body=issue_msg)
                            # variant_bom.activity_schedule(
                            #     'mail.mail_activity_data_todo',
                            #     user_id=self.env.user.id,
                            #     note=_('Fix BoM Issue')
                            # )


                        # hmm = variant_bom.activity_schedule('mail.mail_activity_data_warning',
                        #     summary=summary, 
                        #     note=note,
                        #     )
                        # variant_bom.message_post(body=summary)
                        result.append({'variant': variant, 'issues':issues, 'message': None})
                bom.message_post_with_view(
                    'jt_mrp_bom_templates.message_bom_template_result',
                    values={'result': result,},
                    subtype_id=self.env.ref('mail.mt_note').id)                                
                foo = 2


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    parent_is_template = fields.Boolean('parent_is_template', related="bom_id.is_bom_template", default=False)

    sequence_bis = fields.Integer(compute='_compute_sequence_bis', inverse='_inverse_sequence_bis', string='Sequence')
    
    @api.depends('sequence')
    def _compute_sequence_bis(self):
        for rec in self:
            rec.sequence_bis = rec.sequence

    def _inverse_sequence_bis(self):
        for rec in self:
            rec.sequence = rec.sequence_bis        