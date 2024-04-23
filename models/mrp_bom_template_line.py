import logging
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

class MrpBomTemplateLine(models.Model):
    _name = 'mrp.bom.template.line'
    _description = 'Mrp Bom Template Line'
    _rec_name = "template_id"

    # _order = "sequence, id"
    _check_company_auto = True
    
    def _get_default_product_uom_id(self):
        return self.env['uom.uom'].search([], limit=1, order='id').id

    def _template_id_domain(self):
        domain = [('attribute_line_ids.attribute_id', 'in', self.bom_id.allowed_product_attribute_ids.ids)]
        return domain

    def _extra_attribute_value_ids_domain(self):
        required_attribute_id = self.template_id.valid_product_template_attribute_line_ids.attribute_id - self.allowed_product_attribute_ids
        domain =  [('attribute_id', 'in', required_attribute_id.ids)]
        return domain

    bom_id = fields.Many2one(
        'mrp.bom', 'Parent BoM',
        index=True, ondelete='cascade', required=True)

    template_id = fields.Many2one('product.template', 'Component Template',  required=True, check_company=True,)        
    company_id = fields.Many2one(
        related='bom_id.company_id', store=True, index=True, readonly=True)        
    sequence = fields.Integer(
        'Sequence', default=10,
        help="Gives the sequence order when displaying.")    

    sequence_bis = fields.Integer(compute='_compute_sequence_bis', inverse='_inverse_sequence_bis', string='Sequence')
    
    @api.depends('sequence')
    def _compute_sequence_bis(self):
        for rec in self:
            rec.sequence_bis = rec.sequence

    def _inverse_sequence_bis(self):
        for rec in self:
            rec.sequence = rec.sequence_bis

    product_qty = fields.Float(
        'Quantity', default=1.0,
        digits='Product Unit of Measure', required=True)
    product_uom_id = fields.Many2one(
        'uom.uom', 'Product Unit of Measure',
        default=_get_default_product_uom_id,
        required=True,
        help="Unit of Measure (Unit of Measure) is the unit of measurement for the inventory control", domain="[('category_id', '=', product_uom_category_id)]")
    product_uom_category_id = fields.Many2one(related='template_id.uom_id.category_id')

    allowed_product_attribute_ids = fields.One2many('product.attribute', related="bom_id.allowed_product_attribute_ids")

    possible_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        compute='_compute_possible_product_template_attribute_value_ids', )

    extra_attribute_value_ids = fields.Many2many('product.template.attribute.value', string='Extra Attribute Value', ondelete='restrict', domain="[('id', 'in', possible_template_attribute_value_ids)]")

    applicable_regexp = fields.Char('Component Regexp', help="If filled in, only apply if the regexp matched the default_code of the component")

    optional = fields.Boolean('Optional', default=False, help="Do not create issue if not found")

    ambiguous = fields.Boolean(compute='_compute_ambiguous', string='Ambiguous')
    

    possible_bom_product_template_attribute_value_ids = fields.Many2many(relation="bom_template_possible_rel", related='bom_id.possible_product_template_attribute_value_ids')
    bom_product_template_excl_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value', relation="bom_template_possible_rel3", string="Exclude on Variants", ondelete='restrict',
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants excluded to apply this line.")

    bom_product_template_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value', relation="bom_template_possible_rel2", string="Apply on Variants", ondelete='restrict',
        domain="[('id', 'in', possible_bom_product_template_attribute_value_ids)]",
        help="BOM Product Variants needed to apply this line.")        

    @api.depends('template_id', 'allowed_product_attribute_ids')
    def _compute_possible_product_template_attribute_value_ids(self):
        for line in self:
            first = line.template_id.valid_product_template_attribute_line_ids.filtered(lambda r: r.attribute_id not in line.allowed_product_attribute_ids)
            second = first._without_no_variant_attributes()
            third = second.product_template_value_ids
            fourth = third._only_active()
            line.possible_template_attribute_value_ids = fourth


    @api.depends('allowed_product_attribute_ids')
    def _compute_ambiguous(self):
        for line in self:            
            line_product_attributes = line.template_id.valid_product_template_attribute_line_ids.attribute_id
            missing_attributes = line_product_attributes - line.allowed_product_attribute_ids - line.extra_attribute_value_ids.attribute_id
            if len(missing_attributes) > 0:
                _logger.info("Attribute not found in this product: ambiguous")
                line.ambiguous = True
            else:
                _logger.info("Attribute found not ambiguous")
                line.ambiguous = False

    def _generate_bom_line(self, product):
        self.ensure_one()
        if product not in self.bom_id.product_tmpl_id.product_variant_ids:
             raise ValidationError(_('Product %s is not a variant of %s', product.name, self.bom_id.product_tmpl_id.name))
        
        line_template_attribute_lines = self.template_id.valid_product_template_attribute_line_ids
        # line_template_attributes = line_template_attribute_lines.attribute_id
        product_attribute_lines = product.product_template_variant_value_ids
        # product_attributes = product_attribute_lines.attribute_id

        product_attribue_values = product_attribute_lines.product_attribute_value_id

        template_attribute_values = line_template_attribute_lines.product_template_value_ids.product_attribute_value_id

        attribute_values = product_attribue_values & template_attribute_values

        product_template_attribute_values = line_template_attribute_lines.product_template_value_ids.filtered(lambda r : r.product_attribute_value_id in attribute_values)

        # parent_combination = product_template_attribute_values + self.extra_attribute_value_ids

        # poss = self.template_id._get_possible_variants(parent_combination=parent_combination)

        # foo = self.template_id.product_variant_ids

        # poss2 = foo.filtered(lambda r: len(r.attribute_line_ids - parent_combination) == 0)

        for prod in self.template_id.product_variant_ids:
            values = prod.product_template_variant_value_ids - self.extra_attribute_value_ids
            diff = values - product_template_attribute_values
            if len(diff) == 0:
                return prod

        return None

    @api.model_create_multi
    def create(self, vals):
        res = super().create(vals)
        return res

    def write(self, vals):
        res = super().write(vals)
        return res



